import sys,tempfile,json,threading,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_foundation import wav,form
from lva_system.core import Store,digest,uid
from lva_system.asr import transcribe_case,model_identity,validate_result
from lva_system.asr_worker import atomic

class ASRControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name);self.source=self.p/'source.wav';wav(self.source);self.form=self.p/'form.xlsx';form(self.form)
        self.store=Store(self.p/'store');self.cid=self.store.register(self.form,self.source)['case_id'];self.store.prepare(self.cid,2)
        self.model=self.p/'model';self.model.mkdir();files={}
        for name in ['model.bin','config.json','tokenizer.json']:
            f=self.model/name;f.write_bytes(b'SYNTHETIC_TEST_ONLY');files[name]=digest(f)
        atomic(self.model/'MODEL_MANIFEST.json',{'schema_version':'1.0','repo_id':'SYNTHETIC_TEST_ONLY','revision':'synthetic','files':files})
        self.versions={'faster-whisper':'TEST','ctranslate2':'TEST','av':'TEST','numpy':'TEST'};self.calls=[]
    def tearDown(self):self.store.close();self.tmp.cleanup()
    def fake_engine(self,python,request_path,cancel,progress):
        r=json.loads(Path(request_path).read_text(encoding='utf-8'));self.calls.append(r['role'])
        payload={'schema_version':'1.0','request_fingerprint':r['request_fingerprint'],'role':r['role'],'duration_us':3100000,'engine_versions':self.versions,'segments':[{'utterance_id':uid(),'source_segment_index':0,'text':'SYNTHETIC TEST ONLY','start_us':100000,'end_us':900000,'words':[],'metrics':{},'status':'DRAFT_UNREVIEWED'}]}
        atomic(r['output_path'],payload)
    def run_asr(self,**kwargs):
        return transcribe_case(self.store,self.cid,self.model,'fake-python-not-executed',engine_versions=self.versions,invoke=kwargs.pop('invoke',self.fake_engine),**kwargs)
    def test_archive_exports_and_duplicate_reuse(self):
        r=self.run_asr();self.assertEqual(self.calls,['interviewer','respondent']);self.assertEqual(r['status'],'DRAFT_UNREVIEWED');self.assertEqual(r['new_artifacts'],12)
        exports=self.store.files(self.cid,'transcript_json');self.assertEqual(len(exports),3)
        combined=next(x for x in exports if json.loads(x['metadata'])['selection']=='both');p=self.store.root/combined['path'];j=json.loads(p.read_text(encoding='utf-8'))
        self.assertEqual(j['time_origin'],'ORIGINAL_AUDIO_START');self.assertEqual(len(j['utterances']),2);self.assertEqual(j['utterances'][0]['start_us'],100000)
        count=len(self.store.files(self.cid));self.assertTrue(self.run_asr()['reused']);self.assertEqual(len(self.calls),2);self.assertEqual(len(self.store.files(self.cid)),count);self.assertFalse(self.store.verify(self.cid)['issues'])
    def test_interrupted_second_channel_reuses_first(self):
        def interrupt(p,r,c,progress):
            req=json.loads(Path(r).read_text(encoding='utf-8'))
            if req['role']=='respondent':raise InterruptedError('synthetic interruption')
            self.fake_engine(p,r,c,progress)
        with self.assertRaises(InterruptedError):self.run_asr(invoke=interrupt)
        self.assertEqual(len(self.store.files(self.cid)),4)
        self.run_asr();self.assertEqual(self.calls,['interviewer','respondent'])
    def test_model_corruption_blocks_before_engine(self):
        (self.model/'model.bin').write_bytes(b'changed')
        with self.assertRaises(ValueError):self.run_asr()
        self.assertEqual(self.calls,[])
    def test_checkpoint_corruption_blocks(self):
        def interrupt(p,r,c,progress):
            req=json.loads(Path(r).read_text(encoding='utf-8'))
            if req['role']=='respondent':raise RuntimeError('interruption')
            self.fake_engine(p,r,c,progress)
        with self.assertRaises(RuntimeError):self.run_asr(invoke=interrupt)
        checkpoint=next((self.store.root/'_asr_jobs').rglob('interviewer.json'));checkpoint.write_bytes(b'bad')
        with self.assertRaises(ValueError):self.run_asr()
        self.assertEqual(len(self.store.files(self.cid)),4)
    def test_engine_failure_without_silent_cpu_switch(self):
        def fail(*args):raise RuntimeError('GPU missing')
        with self.assertRaises(RuntimeError):self.run_asr(invoke=fail)
        self.assertEqual(len(self.store.files(self.cid)),4)
    def test_different_device_is_new_run(self):
        self.run_asr();self.run_asr(device='cpu');self.assertEqual(len(self.calls),4);self.assertEqual(len(self.store.files(self.cid,'asr_run')),2)
    def test_cancel_before_work(self):
        cancel=threading.Event();cancel.set()
        with self.assertRaises(InterruptedError):self.run_asr(cancel=cancel)
        self.assertEqual(self.calls,[]);self.assertEqual(len(self.store.files(self.cid)),4)
    def test_journal_recovery_after_asr_prepared(self):
        def fault(phase):
            if phase=='prepared':raise RuntimeError('simulated crash')
        self.store.fault=fault
        with self.assertRaises(RuntimeError):self.run_asr()
        self.store.fault=lambda phase:None;self.store.recover();self.assertFalse(self.store.verify(self.cid)['issues']);self.assertTrue(self.run_asr()['reused']);self.assertEqual(len(self.calls),2)
    def test_invalid_engine_times_never_archive(self):
        def bad(p,r,c,progress):
            self.fake_engine(p,r,c,progress);req=json.loads(Path(r).read_text(encoding='utf-8'));out=Path(req['output_path']);payload=json.loads(out.read_text(encoding='utf-8'));payload['segments'][0]['end_us']=999999999;atomic(out,payload)
        with self.assertRaises(ValueError):self.run_asr(invoke=bad)
        self.assertEqual(len(self.store.files(self.cid)),4)
if __name__=='__main__':unittest.main()
