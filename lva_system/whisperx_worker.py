"""Local CPU WhisperX adapter; archived audio and database are never modified."""
import argparse,copy,gc,hashlib,inspect,importlib.metadata,json,math,os,sys,time
from pathlib import Path
from . import audio
from .core import digest,uid
from .asr_worker import atomic,microseconds

EXPECTED={'whisperx':'3.8.7rc1','faster-whisper':'1.2.1','ctranslate2':'4.8.1','torch':'2.8.0','torchaudio':'2.8.0','numpy':'2.2.6'}

def versions():
    result={name:importlib.metadata.version(name) for name in EXPECTED}
    dist=importlib.metadata.distribution('whisperx')
    direct=dist.read_text('direct_url.json')
    result['_whisperx_install']=json.loads(direct) if direct else None
    package=Path(dist.locate_file('whisperx'));h=hashlib.sha256()
    for p in sorted(package.rglob('*.py')):
        h.update(p.relative_to(package).as_posix().encode());h.update(p.read_bytes())
    result['_whisperx_source_sha256']=h.hexdigest()
    result['_dependency_versions']={d.metadata['Name']:d.version for d in importlib.metadata.distributions() if d.metadata.get('Name')}
    torch_version=Path(importlib.metadata.distribution('torch').locate_file('torch/version.py'))
    result['_torch_build_file_sha256']=digest(torch_version) if torch_version.is_file() else None
    return result

def offline():
    for name in ['HF_HUB_OFFLINE','HF_DATASETS_OFFLINE','TRANSFORMERS_OFFLINE']:os.environ[name]='1'
    os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
    def guard(event,args):
        if event in ('socket.connect','socket.getaddrinfo','urllib.Request'):raise RuntimeError('Network disabled during local ASR; cached models required')
    sys.addaudithook(guard)

def prepare(folder):
    offline();v=versions()
    if (v.get('_whisperx_install') or {}).get('vcs_info',{}).get('commit_id')!='2cfd7b7c5c7bba144954364db747319b50e8232b':raise ValueError('Git commit WhisperX відрізняється від контрольного; середовище не змінено')
    if any(v[k]!=expected for k,expected in EXPECTED.items()):raise ValueError('Версії наявного WhisperX відрізняються від контрольних; середовище не змінено')
    from faster_whisper.utils import download_model
    cached=Path(download_model('large-v3',local_files_only=True)).resolve()
    files={p.name:digest(p) for p in cached.iterdir() if p.is_file() and p.name!='MODEL_MANIFEST.json'}
    for name in ['model.bin','config.json','tokenizer.json']:
        if name not in files:raise ValueError('Кеш large-v3 неповний: '+name)
    dist=importlib.metadata.distribution('whisperx');vad=Path(dist.locate_file('whisperx/assets/pytorch_model.bin'))
    if not vad.is_file():raise ValueError('Немає контрольної Pyannote VAD-моделі у WhisperX assets')
    m={'schema_version':'1.1','repo_id':'Systran/faster-whisper-large-v3','revision':cached.name,
       'storage_dir':str(cached),'files':files,'external_files':{str(vad.resolve()):digest(vad)},'runtime':v}
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    target=folder/'MODEL_MANIFEST.json'
    if target.exists() and json.loads(target.read_text(encoding='utf-8'))!=m:
        raise ValueError('Контрольна модель або середовище змінилися; попередній опис не перезаписано')
    if not target.exists():atomic(target,m)
    return {'status':'LOCAL_REFERENCE_READY','model_descriptor':str(folder)}

def normalize(segments,origin_us,window_end_us,time_status):
    result=[]
    for index,s in enumerate(segments):
        a=origin_us+microseconds(s['start']);raw_b=origin_us+microseconds(s['end'])
        if a<origin_us or a>=window_end_us or raw_b<=a:raise ValueError('Некоректні часові межі WhisperX')
        b=min(raw_b,window_end_us);flags=['TIME_REVIEW_REQUIRED'];words=[]
        if b!=raw_b:flags.append('END_CLIPPED_TO_WINDOW')
        for word in s.get('words',[]):
            w={'word':word.get('word','')}
            if word.get('start') is not None and word.get('end') is not None:
                wa=origin_us+microseconds(word['start']);wb=origin_us+microseconds(word['end'])
                if not origin_us<=wa<=wb<=window_end_us:
                    w['raw_start_us']=wa;w['raw_end_us']=wb;w['time_status']='OUTSIDE_WINDOW';flags.append('WORD_TIME_OUTSIDE_WINDOW')
                else:w.update(start_us=wa,end_us=wb,time_status=time_status)
            else:w['time_status']='MISSING';flags.append('WORD_TIME_MISSING')
            score=word.get('score')
            if score is not None:
                if not math.isfinite(score):raise ValueError('Некоректний alignment score')
                w['alignment_score']=score
            word_flags=[]
            if 'start_us' in w:
                if w['end_us']-w['start_us']>1500000:word_flags.append('WORD_DURATION_LONG')
                if w['start_us']-origin_us<=250000 or window_end_us-w['end_us']<=250000:word_flags.append('WORD_NEAR_WINDOW_EDGE')
                if w['start_us']==w['end_us']:word_flags.append('WORD_ZERO_DURATION')
            if score is not None and score<0.5:word_flags.append('ALIGNMENT_SCORE_LOW')
            w['review_flags']=word_flags
            flags.extend(word_flags)
            words.append(w)
        result.append({'utterance_id':uid(),'source_segment_index':index,'text':s['text'],
                       'start_us':a,'end_us':b,'raw_engine_start_us':a,'raw_engine_end_us':raw_b,
                       'words':words,'metrics':{},'time_status':time_status,
                       'review_flags':sorted(set(flags)),'status':'DRAFT_UNREVIEWED'})
    return result

def align_result(wx,raw,waveform,language,policy,progress):
    if not raw.get('segments'):return raw,{'status':'NOT_APPLICABLE_EMPTY','language':language}
    progress('ALIGNMENT_LOADING');model=None
    try:
        if not language:raise ValueError('Мова не визначена')
        model,metadata=wx.load_align_model(language_code=language,device='cpu')
        config=getattr(model,'config',None)
        provenance={'model_class':type(model).__name__,'name':getattr(config,'_name_or_path',None),'revision':getattr(config,'_commit_hash',None)}
        # Content identity also covers torchaudio aligners lacking a repository revision.
        import torch
        h=hashlib.sha256()
        for name,tensor in sorted(model.state_dict().items()):
            h.update(name.encode());h.update(str(tensor.dtype).encode());h.update(str(tuple(tensor.shape)).encode())
            h.update(tensor.detach().cpu().contiguous().reshape(-1).view(torch.uint8).numpy().tobytes())
        provenance['weights_sha256']=h.hexdigest()
        progress('ALIGNMENT_RUNNING')
        aligned=wx.align(copy.deepcopy(raw['segments']),model,metadata,waveform,'cpu',return_char_alignments=False)
        # Preserve the ASR result if an aligner drops every nonempty utterance.
        if not aligned.get('segments'):raise ValueError('Alignment повернув порожній результат для наявного тексту')
        for s in aligned['segments']:
            if not isinstance(s.get('text'),str) or not math.isfinite(s['start']) or not math.isfinite(s['end']) or s['end']<=s['start']:raise ValueError('Alignment повернув некоректні межі')
        return {**raw,**aligned},{'status':'COMPLETED_UNREVIEWED','language':language,'model':provenance}
    except Exception as e:
        if policy=='require':raise
        return raw,{'status':'FAILED_ASR_TIMES_RETAINED','language':language,'error_type':type(e).__name__,'error':str(e)}
    finally:
        model=None;gc.collect()

def transcribe(request):
    began=time.monotonic();offline()
    if request['device']!='cpu':raise ValueError('Контрольний WhisperX-профіль цього випуску тільки CPU')
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    import whisperx
    info=audio.inspect(request['audio_path']);rate=info['sample_rate']
    if info['channels']!=1:raise ValueError('WhisperX source must be registered mono')
    start=request.get('start_frame',0);end=request.get('end_frame',info['frames'])
    if not 0<=start<end<=info['frames']:raise ValueError('Некоректний інтервал проби')
    with sf.SoundFile(request['audio_path']) as f:
        f.seek(start);samples=f.read(end-start,dtype='float32',always_2d=True)
    if samples.shape!=(end-start,1) or not np.isfinite(samples).all():raise ValueError('Некоректні семпли ASR')
    waveform=samples[:,0]
    if rate!=16000:
        divisor=math.gcd(rate,16000);waveform=resample_poly(waveform,16000//divisor,rate//divisor)
    waveform=np.ascontiguousarray(waveform,dtype=np.float32)
    def progress(state):atomic(request['progress_path'],{'state':state,'segments':0})
    progress('MODEL_LOADING');model_began=time.monotonic()
    kwargs={'compute_type':'int8','language':request['language']}
    if 'local_files_only' in inspect.signature(whisperx.load_model).parameters:kwargs['local_files_only']=True
    model=whisperx.load_model(request['model_path'],'cpu',**kwargs)
    model_seconds=time.monotonic()-model_began
    progress('ASR_RUNNING');asr_began=time.monotonic()
    raw=model.transcribe(waveform,batch_size=4)
    asr_seconds=time.monotonic()-asr_began
    model=None;gc.collect()
    language=raw.get('language') or request['language'];origin=start*1000000//rate;limit=end*1000000//rate
    # Validate ASR before attempting alignment, so fallback can always be trusted.
    asr_segments=normalize(raw.get('segments',[]),origin,limit,'ASR_ESTIMATED')
    alignment_began=time.monotonic()
    aligned,alignment=align_result(whisperx,raw,waveform,language,request['alignment_policy'],progress)
    if alignment['status']=='COMPLETED_UNREVIEWED':
        try:segments=normalize(aligned['segments'],origin,limit,'ALIGNED_UNREVIEWED')
        except Exception as e:
            if request['alignment_policy']=='require':raise
            alignment={'status':'FAILED_ASR_TIMES_RETAINED','language':language,'error_type':type(e).__name__,'error':str(e)};segments=asr_segments
    else:segments=asr_segments
    payload={'schema_version':'1.0','request_fingerprint':request['request_fingerprint'],'role':request['role'],
             'duration_us':info['frames']*1000000//rate,'window':{'start_frame':start,'end_frame':end,'sample_rate':rate,'start_us':origin,'end_us':limit},
             'detected_language':language,'language_probability':None,'engine_versions':versions(),
             'asr_status':'COMPLETED' if segments else 'NO_SPEECH_DETECTED','alignment':alignment,
             'timings_seconds':{'model_loading':round(model_seconds,3),'asr':round(asr_seconds,3),'alignment':round(time.monotonic()-alignment_began,3),'total':round(time.monotonic()-began,3),'selected_audio':(end-start)/rate},'raw_asr_result':raw,'segments':segments,'status':'DRAFT_UNREVIEWED'}
    atomic(request['output_path'],payload);atomic(request['progress_path'],{'state':'DONE','segments':len(segments),'processed_us':limit})

def main():
    p=argparse.ArgumentParser();p.add_argument('--describe',action='store_true');p.add_argument('--prepare');p.add_argument('--request');a=p.parse_args()
    if a.describe:print(json.dumps(versions()));return
    if a.prepare:print(json.dumps(prepare(a.prepare)));return
    if not a.request:p.error('request required')
    transcribe(json.loads(Path(a.request).read_text(encoding='utf-8')))
if __name__=='__main__':main()
