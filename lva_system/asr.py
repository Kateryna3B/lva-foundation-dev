"""Pilot controller: one engine process/channel, verified checkpoints, archive journal."""
import hashlib,json,os,subprocess,threading,time
from pathlib import Path
from .core import digest,dump,uid,now
from .asr_worker import atomic
from .time_input import parse_time_ms

LANGUAGES=[None,'uk','ru','be','az','kk','et']

def model_identity(folder):
    folder=Path(folder).resolve();manifest=folder/'MODEL_MANIFEST.json'
    if not manifest.is_file():raise ValueError('Модель не підготовлена: немає MODEL_MANIFEST.json')
    m=json.loads(manifest.read_text(encoding='utf-8'))
    if m.get('schema_version') not in ['1.0','1.1'] or not m.get('files'):raise ValueError('Невідомий опис моделі')
    storage=Path(m['storage_dir']).resolve() if m['schema_version']=='1.1' else folder
    for required in ['model.bin','config.json','tokenizer.json']:
        if required not in m['files']:raise ValueError('Модель неповна: '+required)
    for name,expected in m['files'].items():
        if Path(name).name!=name:raise ValueError('Некоректне ім’я файла моделі')
        candidate=storage/name
        p=candidate.resolve()
        if (m['schema_version']=='1.0' and (folder not in p.parents or candidate.is_symlink())) or not p.is_file() or digest(p)!=expected:raise ValueError('Цілісність моделі порушено: '+name)
    for name,expected in m.get('external_files',{}).items():
        if not Path(name).is_file() or digest(name)!=expected:raise ValueError('Цілісність VAD-моделі порушено')
    return {'repo_id':m['repo_id'],'revision':m['revision'],'manifest_sha256':digest(manifest),'storage_dir':str(storage)}

def inspect_engine(python,engine='faster-whisper'):
    module='lva_system.whisperx_worker' if engine=='whisperx' else 'lva_system.asr_worker'
    r=subprocess.run([str(python),'-m',module,'--describe'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,encoding='utf-8',timeout=30)
    if r.returncode:raise ValueError('ASR-середовище не готове. Перевірте обраний Python. '+r.stderr[-400:])
    return json.loads(r.stdout)

def invoke_engine(python,request_path,cancel,progress):
    request=json.loads(Path(request_path).read_text(encoding='utf-8'));log=Path(request_path).with_suffix('.log')
    with log.open('w',encoding='utf-8') as stderr:
        module='lva_system.whisperx_worker' if request.get('engine')=='whisperx' else 'lva_system.asr_worker'
        child_env={**os.environ,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'}
        proc=subprocess.Popen([str(python),'-m',module,'--request',str(request_path)],cwd=Path(__file__).resolve().parents[1],stdout=stderr,stderr=stderr,env=child_env)
        try:
            while proc.poll() is None:
                if cancel.is_set():raise InterruptedError('ASR зупинено. Завершені канали збережено; поточний буде виконано заново.')
                p=Path(request['progress_path'])
                update={'state':'PROCESS_STARTING'}
                if p.is_file():
                    try:update=json.loads(p.read_text(encoding='utf-8'))
                    except (ValueError,OSError):pass
                progress({**update,'process_alive':True,'pid':proc.pid,'log_path':str(log)})
                time.sleep(0.25)
            if proc.returncode:raise RuntimeError('ASR-процес завершився з помилкою. Подробиці у локальному '+str(log)+'. CPU-режим не підставлено автоматично.')
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:proc.wait(timeout=10)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()

def validate_result(payload,request,duration):
    if payload.get('schema_version')!='1.0' or payload.get('request_fingerprint')!=request['request_fingerprint'] or payload.get('role')!=request['role'] or payload.get('duration_us')!=duration or not isinstance(payload.get('segments'),list):raise ValueError('ASR result identity mismatch')
    seen=set()
    if request.get('engine')=='whisperx':
        if payload.get('asr_status') not in ['COMPLETED','NO_SPEECH_DETECTED'] or payload.get('alignment',{}).get('status') not in ['COMPLETED_UNREVIEWED','FAILED_ASR_TIMES_RETAINED','NOT_APPLICABLE_EMPTY']:raise ValueError('Немає явного статусу ASR/alignment')
        if request['alignment_policy']=='require' and payload['segments'] and payload['alignment']['status']!='COMPLETED_UNREVIEWED':raise ValueError('Обов’язковий alignment не виконано')
    start=request.get('start_frame',0)*1000000//request.get('sample_rate',1)
    end=request.get('end_frame',duration)*1000000//request['sample_rate'] if 'sample_rate' in request else duration
    for s in payload['segments']:
        if not isinstance(s.get('text'),str) or type(s.get('start_us'))!=int or type(s.get('end_us'))!=int or not start<=s['start_us']<s['end_us']<=end or not s.get('utterance_id') or s['utterance_id'] in seen:raise ValueError('Некоректний сегмент ASR')
        if request.get('engine')=='whisperx' and s.get('time_status')!=('ALIGNED_UNREVIEWED' if payload['alignment']['status']=='COMPLETED_UNREVIEWED' else 'ASR_ESTIMATED'):raise ValueError('Статус часу суперечить alignment')
        seen.add(s['utterance_id'])
    return payload

def stamp(us):
    ms=us//1000;return f'{ms//60000:02}:{ms//1000%60:02}.{ms%1000:03}'

def transcribe_case(store,cid,model_path,python,device='cuda',language=None,cancel=None,progress=None,engine_versions=None,invoke=None,dll_dirs=None,engine='faster-whisper',alignment_policy='keep_asr',interval_times=None,revision_token=None):
    if device not in ['cuda','cpu'] or language not in LANGUAGES:raise ValueError('Невідомий ASR-профіль')
    if engine not in ['faster-whisper','whisperx'] or alignment_policy not in ['keep_asr','require']:raise ValueError('Невідомий рушій або правило alignment')
    if engine=='whisperx' and device!='cpu':raise ValueError('WhisperX-профіль цього випуску працює тільки на CPU')
    if interval_times and engine!='whisperx':raise ValueError('Коротка проба доступна для WhisperX')
    cancel=cancel or threading.Event();progress=progress or (lambda data:None);invoke=invoke or invoke_engine
    model=model_identity(model_path);versions=engine_versions if engine_versions is not None else inspect_engine(python,engine)
    descriptor=json.loads((Path(model_path)/'MODEL_MANIFEST.json').read_text(encoding='utf-8'))
    if engine=='whisperx' and descriptor.get('runtime')!=versions:raise ValueError('WhisperX-середовище змінилося після підготовки опису моделі')
    with store.locked():
        cid=store.case(cid)['id'];store.require_valid(cid);sources=[]
        for role in ['interviewer','respondent']:
            found=store.files(cid,role)
            if len(found)!=1:raise ValueError('Спочатку підтвердьте й витягніть обидва канали')
            sources.append(found[0])
        options={'device':device,'compute_type':'int8_float16' if device=='cuda' else 'int8','language':language,'beam_size':5,'temperature':0.0,'word_timestamps':True,'vad_filter':False,'condition_on_previous_text':True,'controller_version':'0.2.0','task':'transcribe','dll_dirs':list(dll_dirs or [])}
        if engine=='whisperx':options={'engine':'whisperx','device':'cpu','compute_type':'int8','batch_size':4,'language':language,'vad':'pyannote_default','asr_options':'installed_whisperx_defaults','alignment_policy':alignment_policy,'controller_version':'0.2.2','interval_ms':[parse_time_ms(v) for v in interval_times] if interval_times else None,'revision_token':revision_token}
        windows={}
        for r in sources:
            meta=json.loads(r['metadata']);a,b=0,meta['frames']
            if interval_times:
                if len(options['interval_ms'])!=2:raise ValueError('Потрібні початок і кінець проби')
                a,b=[(ms*meta['sample_rate']+500)//1000 for ms in options['interval_ms']]
                if not 0<=a<b<=meta['frames']:raise ValueError('Проба виходить за межі аудіо або має порожній інтервал')
                if b-a>120*meta['sample_rate']:raise ValueError('Коротка проба має тривати не більш як 2 хвилини')
            windows[r['kind']]={'start_frame':a,'end_frame':b,'sample_rate':meta['sample_rate']}
        identity={'case_id':cid,'sources':[{'artifact_id':r['id'],'sha256':r['sha256'],'role':r['kind']} for r in sources],'model':model,'engine_versions':versions,'options':options}
        fp=hashlib.sha256(dump(identity).encode()).hexdigest()
        previous=[r for r in store.files(cid,'asr_run') if json.loads(r['metadata']).get('fingerprint')==fp]
        if previous:
            old=json.loads((store.root/previous[0]['path']).read_text(encoding='utf-8'))
            return {'case_id':cid,'reused':True,'status':'DRAFT_UNREVIEWED','run_artifact_id':previous[0]['id'],'scope':old.get('scope'),'channel_statuses':old.get('channel_statuses'),'warnings':old.get('warnings')}
        job=store.root/'_asr_jobs'/fp;job.mkdir(parents=True,exist_ok=True);job_meta=job/'job.json'
        if job_meta.exists():
            j=json.loads(job_meta.read_text(encoding='utf-8'))
            if j['identity']!=identity:raise ValueError('Checkpoint identity mismatch')
        else:
            j={'identity':identity,'run_id':uid(),'started':now()};atomic(job_meta,j)
        utterances=[];raw_outputs=[];empty_roles=[];channel_statuses={}
        for r in sources:
            if cancel.is_set():raise InterruptedError('ASR зупинено до наступного каналу')
            meta=json.loads(r['metadata']);duration=meta['frames']*1000000//meta['sample_rate'];role=r['kind'];out=job/(role+'.json');done=job/(role+'.done.json')
            req={**options,'model_path':model['storage_dir'],'audio_path':str(store.root/r['path']),'output_path':str(out),'progress_path':str(job/(role+'.progress.json')),'request_fingerprint':fp+':'+role,'role':role}
            if engine=='whisperx':req.update(windows[role])
            if done.exists():
                checkpoint=json.loads(done.read_text(encoding='utf-8'))
                if not out.is_file() or digest(out)!=checkpoint['sha256']:raise ValueError('ASR checkpoint пошкоджений; його не перезаписано')
                progress({'role':role,'state':'CHECKPOINT_REUSED'})
            else:
                out.unlink(missing_ok=True);rp=job/(role+'.request.json');atomic(rp,req)
                invoke(python,rp,cancel,lambda d:progress({'role':role,**d}))
                if not out.is_file():raise ValueError('ASR-процес не створив результат')
            payload=validate_result(json.loads(out.read_text(encoding='utf-8')),req,duration)
            if payload.get('engine_versions')!=versions:raise ValueError('ASR engine versions changed')
            if not payload['segments']:empty_roles.append(role)
            channel_statuses[role]={'asr_status':payload.get('asr_status','COMPLETED' if payload['segments'] else 'NO_SPEECH_DETECTED'),'alignment':payload.get('alignment',{'status':'NOT_REQUESTED'}),'timings_seconds':payload.get('timings_seconds')}
            if not done.exists():atomic(done,{'sha256':digest(out),'request_fingerprint':req['request_fingerprint']})
            raw_outputs.append(out)
            for s in payload['segments']:utterances.append({**s,'role':role,'source_artifact_id':r['id'],'source_channel':meta['source_channel']})
        store.require_valid(cid)
        if model_identity(model_path)!=model:raise ValueError('Модель змінилася під час ASR')
        if len({s['utterance_id'] for s in utterances})!=len(utterances):raise ValueError('Повторний UUID між каналами ASR')
        utterances.sort(key=lambda s:(s['start_us'],s['role'],s['source_segment_index']))
        op,stage=store.begin(cid);files=[]
        run={'schema_version':'1.0','run_id':j['run_id'],'fingerprint':fp,'started':j['started'],'completed':now(),'identity':identity,'status':'DRAFT_UNREVIEWED','warnings':['ASR_TIMES_REQUIRE_REVIEW']+['EMPTY_CHANNEL:'+role for role in empty_roles]}
        run['channel_statuses']=channel_statuses;run['scope']='SHORT_SPEECH_TEST' if interval_times else 'FULL_CHANNELS';run['windows']=windows
        for role,s in channel_statuses.items():
            if s['alignment']['status']=='FAILED_ASR_TIMES_RETAINED':run['warnings'].append('ALIGNMENT_FAILED:'+role)
        path=stage/'asr_run.json';atomic(path,run);files.append(store.spec(cid,stage,path,'asr_run',{'fingerprint':fp,'run_id':j['run_id'],'status':'DRAFT_UNREVIEWED'}))
        for src in raw_outputs:
            path=stage/('raw_'+src.name);store.copy(src,path);files.append(store.spec(cid,stage,path,'asr_raw',{'run_id':j['run_id'],'role':src.stem}))
        for selection in ['both','interviewer','respondent']:
            selected=[s for s in utterances if selection=='both' or s['role']==selection]
            data={'schema_version':'1.0','case_id':cid,'run_id':j['run_id'],'selection':selection,'time_origin':'ORIGINAL_AUDIO_START','status':'DRAFT_UNREVIEWED','scope':run['scope'],'channel_statuses':channel_statuses,'utterances':selected}
            header='Чернетка ASR — потребує перевірки\nОбласть: '+run['scope']+'\n'+'\n'.join(role+': ASR='+s['asr_status']+', alignment='+s['alignment']['status'] for role,s in channel_statuses.items())
            text=header+'\n\n'+'\n'.join(f"[{stamp(s['start_us'])} — {stamp(s['end_us'])}] {s['role']} ({s.get('time_status','ASR_ESTIMATED')}): {s['text'].strip()} [review: {', '.join(s.get('review_flags', []))}]" for s in selected)
            for ext in ['json','txt','md']:
                path=stage/(selection+'.'+ext)
                if ext=='json':atomic(path,data)
                else:path.write_text(('# Чернетка транскрипції\n\n' if ext=='md' else '')+text+'\n',encoding='utf-8')
                files.append(store.spec(cid,stage,path,'transcript_'+ext,{'run_id':j['run_id'],'selection':selection,'status':'DRAFT_UNREVIEWED'}))
        store.commit_plan(op,{'case_id':cid,'files':files,'event':'ASR_DRAFT_IMPORTED'})
        review_files=[str(store.root/r['path']) for r in store.files(cid) if r['kind'] in ['transcript_txt','transcript_json','transcript_md'] and json.loads(r['metadata']).get('run_id')==j['run_id'] and json.loads(r['metadata']).get('selection')=='both']
        return {'review_files':review_files,'case_id':cid,'reused':False,'run_id':j['run_id'],'utterance_count':len(utterances),'new_artifacts':len(files),'status':'DRAFT_UNREVIEWED','scope':run['scope'],'channel_statuses':channel_statuses,'warnings':run['warnings']}
