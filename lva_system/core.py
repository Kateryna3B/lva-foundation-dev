"""Local pilot store: journaled file promotions and transactional registry."""
import base64,contextlib,hashlib,json,os,shutil,sqlite3,uuid
from pathlib import Path
from datetime import datetime,timezone
from . import audio,intake,lva_csv,time_input

def uid():return str(uuid.uuid4())
def dump(v):return json.dumps(v,ensure_ascii=False,sort_keys=True)
def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def now():return datetime.now(timezone.utc).isoformat()

class Store:
    def __init__(self,root):
        self.root=Path(root).resolve()
        if str(root).startswith(('\\\\','//')):raise ValueError('Реєстр повинен бути на локальному диску')
        self.root.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.root/'registry.sqlite3',timeout=5)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON');self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        version=self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0,1):raise ValueError('Непідтримувана версія реєстру')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY,code TEXT UNIQUE,source_hash TEXT,form_hash TEXT,data TEXT);
        CREATE TABLE IF NOT EXISTS people(id TEXT PRIMARY KEY,alias TEXT,note TEXT);
        CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY,case_id TEXT REFERENCES cases(id),kind TEXT,path TEXT UNIQUE,sha256 TEXT,metadata TEXT);
        CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY,case_id TEXT,state TEXT,plan TEXT,created TEXT);
        CREATE TABLE IF NOT EXISTS audit(id TEXT PRIMARY KEY,case_id TEXT,event TEXT,created TEXT);
        PRAGMA user_version=1;''')
        self.db.commit();self.fault=lambda phase:None
    def close(self):self.db.close()
    @contextlib.contextmanager
    def locked(self):
        with open(self.root/'writer.lock','a+b') as f:
            f.seek(0);f.write(b'0');f.flush();f.seek(0)
            try:
                if os.name=='nt':
                    import msvcrt;msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl;fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError as e:raise RuntimeError('Інша операція вже працює з цим реєстром') from e
            try:yield
            finally:
                f.seek(0)
                if os.name=='nt':msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
                else:fcntl.flock(f,fcntl.LOCK_UN)
    def case(self,cid):
        r=self.db.execute('SELECT * FROM cases WHERE id=? OR code=?',(cid,cid)).fetchone()
        if r is None:raise ValueError('Справу не знайдено')
        return dict(r)
    def files(self,cid,kind=None):
        c=self.case(cid)
        rows=self.db.execute('SELECT * FROM artifacts WHERE case_id=? ORDER BY rowid',(c['id'],)).fetchall()
        return [dict(r) for r in rows if kind is None or r['kind']==kind]
    def verify(self,cid):
        issues=[]
        for r in self.files(cid):
            p=self.root/r['path']
            if not p.is_file():issues.append({'artifact_id':r['id'],'issue':'MISSING'})
            elif digest(p)!=r['sha256']:issues.append({'artifact_id':r['id'],'issue':'HASH_MISMATCH'})
        return {'case_id':self.case(cid)['id'],'artifact_count':len(self.files(cid)),'issues':issues}
    def require_valid(self,cid):
        report=self.verify(cid)
        if report['issues']:raise ValueError('Цілісність порушено: '+dump(report))
    def begin(self,cid):
        op=uid();stage=self.root/'_staging'/op;stage.mkdir(parents=True)
        with self.db:self.db.execute('INSERT INTO operations VALUES(?,?,?,?,?)',(op,cid,'WRITING',None,now()))
        return op,stage
    def spec(self,cid,stage,path,kind,metadata):
        aid=uid();return dict(id=aid,case_id=cid,kind=kind,path=f'cases/{cid}/{aid}{Path(path).suffix}',stage=str(Path(path).relative_to(stage)),sha256=digest(path),metadata=dump(metadata))
    def copy(self,source,target):
        before=digest(source)
        with open(source,'rb') as src,open(target,'xb') as out:
            shutil.copyfileobj(src,out,1024*1024);out.flush();os.fsync(out.fileno())
        if digest(source)!=before or digest(target)!=before:raise ValueError('Джерело змінилося під час копіювання')
        return before
    def commit_plan(self,op,plan):
        with self.db:self.db.execute('UPDATE operations SET state=?,plan=? WHERE id=?',('PREPARED',dump(plan),op))
        self.fault('prepared');self.finish(op,plan)
    def finish(self,op,plan):
        stage=self.root/'_staging'/op
        for r in plan['files']:
            target=self.root/r['path'];target.parent.mkdir(parents=True,exist_ok=True)
            source=stage/r['stage']
            if target.exists():
                if digest(target)!=r['sha256']:raise ValueError('Конфлікт або пошкодження кінцевого файла')
            else:
                if not source.is_file() or digest(source)!=r['sha256']:raise ValueError('Пошкоджений staging; автоматичне відновлення заблоковано')
                # Exclusive creation: never overwrite an existing archive item.
                with open(source,'rb') as src,open(target,'xb') as dst:
                    shutil.copyfileobj(src,dst,1024*1024);dst.flush();os.fsync(dst.fileno())
                if digest(target)!=r['sha256']:raise ValueError('Помилка перевірки записаного файла')
            self.fault('promoted')
        with self.db:
            if 'case' in plan:
                c=plan['case'];self.db.execute('INSERT INTO cases VALUES(?,?,?,?,?)',tuple(c[k] for k in ['id','code','source_hash','form_hash','data']))
                for p in plan['people']:self.db.execute('INSERT INTO people VALUES(?,?,?)',(p['id'],p['alias'],p['note']))
            for r in plan['files']:
                self.db.execute('INSERT INTO artifacts VALUES(?,?,?,?,?,?)',tuple(r[k] for k in ['id','case_id','kind','path','sha256','metadata']))
            self.db.execute('UPDATE operations SET state=? WHERE id=?',('COMMITTED',op))
            self.db.execute('INSERT INTO audit VALUES(?,?,?,?)',(uid(),plan['case_id'],plan['event'],now()))
        self.fault('committed');self.manifest(plan['case_id']);shutil.rmtree(stage)
    def manifest(self,cid):
        c=self.case(cid);p=self.root/'cases'/c['id']/'manifest.json';p.parent.mkdir(parents=True,exist_ok=True)
        payload={'schema_version':'1.0','case':{**c,'data':json.loads(c['data'])},'artifacts':self.files(cid)}
        tmp=p.with_suffix('.tmp');tmp.write_text(dump(payload),encoding='utf-8');os.replace(tmp,p)
    def recover(self):
        with self.locked():
            result=[]
            for row in self.db.execute("SELECT * FROM operations WHERE state!='COMMITTED'").fetchall():
                if row['plan']:
                    self.finish(row['id'],json.loads(row['plan']));result.append({'operation_id':row['id'],'state':'RECOVERED'})
                else:result.append({'operation_id':row['id'],'state':'INTERRUPTED_RETAINED'})
            for c in self.db.execute('SELECT id FROM cases').fetchall():self.manifest(c['id'])
            for r in self.db.execute("SELECT id FROM operations WHERE state='COMMITTED'"):
                stage=self.root/'_staging'/r['id']
                if stage.exists():shutil.rmtree(stage)
            return result
    def register(self,form,audio_path,allow_new_case=False):
        data=intake.read_form(form);info=audio.inspect(audio_path);source_hash=digest(audio_path)
        fingerprint=hashlib.sha256(dump(data).encode()).hexdigest()
        with self.locked():
            old=self.db.execute('SELECT id FROM cases WHERE source_hash=? AND form_hash=?',(source_hash,fingerprint)).fetchone()
            if old:self.require_valid(old['id']);return {'case_id':old['id'],'reused':True}
            if not allow_new_case and self.db.execute('SELECT 1 FROM cases WHERE source_hash=?',(source_hash,)).fetchone():raise ValueError('Таке аудіо вже зареєстровано з іншим бланком; потрібен --allow-new-case')
            people=[]
            for role in ('requester','respondent'):
                if data[role+'_mode']=='select':
                    if not self.db.execute('SELECT 1 FROM people WHERE id=?',(data[role+'_id'],)).fetchone():raise ValueError('Невідомий person_id')
                else:
                    pid=uid();people.append(dict(id=pid,alias=data[role+'_alias'],note=data[role+'_note']));data[role+'_id']=pid
            cid=uid();op,stage=self.begin(cid)
            wav=stage/'original.wav';actual_hash=self.copy(audio_path,wav)
            if actual_hash!=source_hash:raise ValueError('Аудіо змінилося після первинної перевірки')
            if audio.inspect(wav)!=info:raise ValueError('Метадані аудіо змінилися')
            xls=stage/'intake.xlsx';self.copy(form,xls)
            if hashlib.sha256(dump(intake.read_form(xls)).encode()).hexdigest()!=fingerprint:raise ValueError('Бланк змінився після перевірки')
            data['audio']=info;data['stage']='RECEIVED'
            if info['frames']>3600*info['sample_rate']:data['stage']='DURATION_REVIEW_REQUIRED'
            elif info['channels']!=2 or data['channel_scheme'] in ('mixed','unknown'):data['stage']='CHANNEL_REVIEW_REQUIRED'
            c=dict(id=cid,code='C'+base64.b32encode(uuid.UUID(cid).bytes).decode().rstrip('='),source_hash=source_hash,form_hash=fingerprint,data=dump(data))
            files=[self.spec(cid,stage,wav,'original',info),self.spec(cid,stage,xls,'intake_form',{'schema_version':'1.0'})]
            self.commit_plan(op,dict(case_id=cid,case=c,people=people,files=files,event='REGISTERED'))
            return {'case_id':cid,'case_code':c['code'],'reused':False,'stage':data['stage']}
    def prepare(self,cid,respondent_channel):
        with self.locked():
            c=self.case(cid);cid=c['id'];self.require_valid(cid);src=self.root/self.files(cid,'original')[0]['path'];info=audio.inspect(src)
            if info['channels']!=2:raise ValueError('Потрібне стерео з двома окремими каналами')
            if respondent_channel not in (1,2):raise ValueError('Канал має бути 1 або 2')
            if json.loads(c['data'])['channel_scheme']=='mixed':raise ValueError('Змішаний запис потребує окремого маршруту')
            audio.count_parts(info['frames'],info['sample_rate'])
            existing=self.files(cid,'respondent')
            if existing:
                if json.loads(existing[0]['metadata'])['source_channel']!=respondent_channel:raise ValueError('Інший канал уже підтверджено; потрібна майбутня функція ревізії')
                return {'case_id':cid,'reused':True}
            op,stage=self.begin(cid);files=[]
            for kind,ch in [('respondent',respondent_channel),('interviewer',3-respondent_channel)]:
                p=stage/(kind+'.wav');meta=audio.write_channel(src,p,ch);meta['source_channel']=ch;meta['normalization']=False
                files.append(self.spec(cid,stage,p,kind,meta))
            self.require_valid(cid)
            self.commit_plan(op,dict(case_id=cid,files=files,event='CHANNELS_CONFIRMED'))
            return {'case_id':cid,'reused':False,'suggested_boundaries_frames':audio.equal_boundaries(info['frames'],info['sample_rate']),
                    'suggested_internal_times':self.parts_plan(cid)['suggested_internal_times']}
    def parts_plan(self,cid):
        cid=self.case(cid)['id'];r=self.files(cid,'respondent')
        if not r:raise ValueError('Спочатку підтвердьте канал респондента')
        info=json.loads(r[0]['metadata']);frames=info['frames'];rate=info['sample_rate']
        n=audio.count_parts(frames,rate);existing=self.files(cid,'part')
        ordered=sorted(existing,key=lambda r:json.loads(r['metadata'])['part_number'])
        return {'case_id':cid,'part_count':n,'duration':time_input.format_time(frames,rate),
                'suggested_internal_times':[time_input.format_time(v,rate) for v in audio.equal_boundaries(frames,rate)[1:-1]],
                'existing_parts':[{'part_number':json.loads(r['metadata'])['part_number'],'start':time_input.format_time(json.loads(r['metadata'])['start_frame'],rate),'end':time_input.format_time(json.loads(r['metadata'])['end_frame'],rate)} for r in ordered]}
    def parts_at_times(self,cid,values):
        r=self.files(cid,'respondent')
        if not r:raise ValueError('Спочатку підтвердьте канал респондента')
        info=json.loads(r[0]['metadata'])
        bounds,context=time_input.boundaries_from_times(values,info['frames'],info['sample_rate'],audio.count_parts(info['frames'],info['sample_rate']))
        return self.parts(cid,bounds,time_context=context)
    def parts(self,cid,boundaries,time_context=None):
        with self.locked():
            cid=self.case(cid)['id'];self.require_valid(cid);r=self.files(cid,'respondent')
            if not r:raise ValueError('Спочатку підтвердьте канал респондента')
            src=self.root/r[0]['path'];info=audio.inspect(src);n=audio.count_parts(info['frames'],info['sample_rate'])
            if len(boundaries)!=n+1 or boundaries[0]!=0 or boundaries[-1]!=info['frames'] or any(type(v)!=int for v in boundaries) or any(a>=b for a,b in zip(boundaries,boundaries[1:])):raise ValueError('Межі мають покривати всі кадри без пропусків і повторів')
            if self.files(cid,'part'):raise ValueError('Частини вже створено; зміна меж потребує майбутньої функції ревізії')
            op,stage=self.begin(cid);files=[]
            for i,(a,b) in enumerate(zip(boundaries,boundaries[1:]),1):
                p=stage/f'part_{i}.wav';meta=audio.write_channel(src,p,1,a,b);meta.update(start_frame=a,end_frame=b,original_sample_rate=info['sample_rate'],part_number=i,boundaries_status='MANUALLY_CONFIRMED')
                if time_context is not None:meta['time_input']=time_context
                files.append(self.spec(cid,stage,p,'part',meta))
            self.require_valid(cid)
            self.commit_plan(op,dict(case_id=cid,files=files,event='PART_BOUNDARIES_CONFIRMED'))
            return {'case_id':cid,'parts':len(files)}
    def import_lva(self,cid,input_wav,csv_path,part_id=None,legacy_full=False):
        if (part_id is None)==(not legacy_full):raise ValueError('Виберіть part_id або legacy_full')
        raw=Path(csv_path).read_bytes();parsed=lva_csv.parse(raw);csv_hash=hashlib.sha256(raw).hexdigest();info=audio.inspect(input_wav)
        with self.locked():
            cid=self.case(cid)['id'];self.require_valid(cid)
            scope=self.files(cid,'original') if legacy_full else [r for r in self.files(cid,'part') if r['id']==part_id]
            if not scope:raise ValueError('Частину не знайдено')
            expected=json.loads(scope[0]['metadata'])
            if info['frames']*expected['sample_rate']!=expected['frames']*info['sample_rate']:raise ValueError('Тривалість входу LVA не відповідає вибраній області')
            if max(s['candidate_end_us'] for s in parsed['segments'])>info['frames']*1000000//info['sample_rate']:raise ValueError('Сегмент виходить за тривалість WAV')
            op,stage=self.begin(cid);files=[]
            for source,name,kind,meta in [(input_wav,'lva_input.wav','lva_input',{'audio':info,'scope_artifact_id':scope[0]['id'],'legacy_full':legacy_full,'processing':'USER_SUPPLIED_UNVERIFIED'}),(csv_path,'lva.csv','lva_csv',{'profile':parsed['profile_id'],'time_status':'UNVERIFIED'})]:
                p=stage/name;self.copy(source,p)
                if kind=='lva_csv' and digest(p)!=csv_hash:raise ValueError('CSV змінився після розбору')
                if kind=='lva_input' and audio.inspect(p)!=info:raise ValueError('WAV LVA змінився після перевірки')
                files.append(self.spec(cid,stage,p,kind,meta))
            parsed['input_artifact_id']=files[0]['id'];parsed['scope_artifact_id']=scope[0]['id']
            for s in parsed['segments']:s['segment_id']=uid()
            p=stage/'segments.json';p.write_text(dump(parsed),encoding='utf-8');files.append(self.spec(cid,stage,p,'lva_segments',{'time_status':'UNVERIFIED','segment_count':len(parsed['segments'])}))
            self.commit_plan(op,dict(case_id=cid,files=files,event='LVA_RAW_IMPORTED_UNVERIFIED'))
            return {'case_id':cid,'segment_count':len(parsed['segments']),'time_status':'UNVERIFIED'}
    def backup(self,destination):
        parent=Path(destination).resolve()
        if parent==self.root or self.root in parent.parents:raise ValueError('Резервування має бути поза робочим каталогом')
        with self.locked():
            if self.db.execute("SELECT 1 FROM operations WHERE state='PREPARED'").fetchone():raise ValueError('Спочатку виконайте recover')
            for c in self.db.execute('SELECT id FROM cases'):self.require_valid(c['id'])
            target=parent/('backup_'+uid());target.mkdir(parents=True);dest=sqlite3.connect(target/'registry.sqlite3')
            try:self.db.backup(dest)
            finally:dest.close()
            checks={}
            for r in self.db.execute('SELECT * FROM artifacts'):
                p=target/r['path'];p.parent.mkdir(parents=True,exist_ok=True);self.copy(self.root/r['path'],p)
                if digest(p)!=r['sha256']:raise ValueError('Джерело змінилося під час резервування')
                checks[r['path']]=r['sha256']
            checks['registry.sqlite3']=digest(target/'registry.sqlite3')
            (target/'COMPLETE.json').write_text(dump({'schema_version':'1.0','created':now(),'checksums':checks}),encoding='utf-8')
            return {'backup_path':str(target),'file_count':len(checks)}
