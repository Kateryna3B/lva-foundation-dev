import copy,json,sys,types,unittest
from pathlib import Path
from unittest.mock import patch
import test_asr as reference_tests
from lva_system.asr_worker import atomic
from lva_system.whisperx_worker import normalize,align_result
from lva_system.asr import model_identity
from lva_system.core import digest

class WhisperXIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=reference_tests.ASRControllerTests();self.fixture.setUp();self.f=self.fixture
        m=json.loads((self.f.model/'MODEL_MANIFEST.json').read_text());m['runtime']=self.f.versions
        atomic(self.f.model/'MODEL_MANIFEST.json',m)
    def tearDown(self):self.fixture.tearDown()
    def engine(self,p,r,c,progress):
        self.f.fake_engine(p,r,c,progress);req=json.loads(Path(r).read_text());out=Path(req['output_path']);data=json.loads(out.read_text())
        start=req['start_frame']*1000000//req['sample_rate']
        for segment in data['segments']:
            segment['start_us']+=start;segment['end_us']+=start;segment['time_status']='ASR_ESTIMATED'
        data['asr_status']='COMPLETED';data['alignment']={'status':'FAILED_ASR_TIMES_RETAINED','language':'ru','error_type':'ValueError','error':'SYNTHETIC MISSING ALIGNER'}
        atomic(out,data)
    def run_asr(self,**kwargs):return self.f.run_asr(engine='whisperx',device='cpu',invoke=kwargs.pop('invoke',self.engine),**kwargs)
    def test_alignment_failure_visible_in_all_exports(self):
        result=self.run_asr(language='ru');self.assertIn('ALIGNMENT_FAILED:respondent',result['warnings'])
        for artifact in self.f.store.files(self.f.cid,'transcript_txt'):
            text=(self.f.store.root/artifact['path']).read_text();self.assertIn('FAILED_ASR_TIMES_RETAINED',text);self.assertIn('ASR_ESTIMATED',text)
        self.assertEqual(self.run_asr(language='ru')['channel_statuses']['respondent']['alignment']['status'],'FAILED_ASR_TIMES_RETAINED')
    def test_required_alignment_blocks_archive(self):
        with self.assertRaises(ValueError):self.run_asr(alignment_policy='require')
        self.assertEqual(len(self.f.store.files(self.f.cid)),4)
    def test_short_test_keeps_original_time_and_distinct_full_run(self):
        result=self.run_asr(interval_times=('00:01','00:02'));self.assertEqual(result['scope'],'SHORT_SPEECH_TEST')
        exports=self.f.store.files(self.f.cid,'transcript_json')
        for artifact in exports:
            data=json.loads((self.f.store.root/artifact['path']).read_text());self.assertEqual(data['utterances'][0]['start_us'],1100000)
        self.run_asr();self.assertEqual(len(self.f.store.files(self.f.cid,'asr_run')),2)
    def test_short_interval_outside_audio_blocks_engine(self):
        with self.assertRaises(ValueError):self.run_asr(interval_times=('00:01','00:05'))
        self.assertEqual(self.f.calls,[])
    def test_alignment_revision_retains_previous_archive(self):
        first=self.run_asr();old={r['id']:r['sha256'] for r in self.f.store.files(self.f.cid)}
        self.run_asr(revision_token='SYNTHETIC_SECOND_REVISION');self.assertEqual(len(self.f.store.files(self.f.cid,'asr_run')),2)
        self.assertTrue(all(old[r['id']]==r['sha256'] for r in self.f.store.files(self.f.cid) if r['id'] in old))
    def test_environment_change_blocks_reference(self):
        self.f.versions={**self.f.versions,'whisperx':'CHANGED'}
        with self.assertRaises(ValueError):self.run_asr()
        self.assertEqual(self.f.calls,[])
    def test_cached_weights_descriptor_and_vad_integrity(self):
        descriptor=self.f.p/'reference_descriptor';descriptor.mkdir();vad=self.f.p/'fake_vad.bin';vad.write_bytes(b'SYNTHETIC VAD')
        manifest=json.loads((self.f.model/'MODEL_MANIFEST.json').read_text());manifest.update(schema_version='1.1',storage_dir=str(self.f.model),external_files={str(vad):digest(vad)})
        atomic(descriptor/'MODEL_MANIFEST.json',manifest)
        self.assertEqual(model_identity(descriptor)['storage_dir'],str(self.f.model))
        vad.write_bytes(b'CORRUPTED')
        with self.assertRaises(ValueError):model_identity(descriptor)
    def test_segment_outside_short_window_is_rejected(self):
        def wrong(*args):
            self.engine(*args);req=json.loads(Path(args[1]).read_text());path=Path(req['output_path']);data=json.loads(path.read_text());data['segments'][0]['start_us']=100000;atomic(path,data)
        with self.assertRaises(ValueError):self.run_asr(interval_times=('00:01','00:02'),invoke=wrong)
        self.assertEqual(len(self.f.store.files(self.f.cid)),4)
    def test_alignment_time_label_cannot_claim_success_after_failure(self):
        def wrong(*args):
            self.engine(*args);req=json.loads(Path(args[1]).read_text());path=Path(req['output_path']);data=json.loads(path.read_text());data['segments'][0]['time_status']='ALIGNED_UNREVIEWED';atomic(path,data)
        with self.assertRaises(ValueError):self.run_asr(invoke=wrong)
        self.assertEqual(len(self.f.store.files(self.f.cid)),4)

class AlignmentAdapterTests(unittest.TestCase):
    def test_actual_alignment_failure_preserves_asr_input(self):
        raw={'language':'ru','segments':[{'start':0.1,'end':0.9,'text':'SYNTHETIC'}]};before=copy.deepcopy(raw)
        wx=types.SimpleNamespace(load_align_model=lambda **kw:(_ for _ in ()).throw(ValueError('model absent')))
        result,status=align_result(wx,raw,None,'ru','keep_asr',lambda state:None)
        self.assertEqual(result,before);self.assertEqual(raw,before);self.assertEqual(status['status'],'FAILED_ASR_TIMES_RETAINED')
        with self.assertRaises(ValueError):align_result(wx,raw,None,'ru','require',lambda state:None)
    def test_alignment_does_not_modify_raw_asr_and_records_provenance(self):
        raw={'language':'uk','segments':[{'start':0.1,'end':0.9,'text':'SYNTHETIC'}]};before=copy.deepcopy(raw)
        model=types.SimpleNamespace(config=types.SimpleNamespace(_name_or_path='SYNTHETIC',_commit_hash='test'),state_dict=lambda:{})
        def align(segments,*a,**kw):segments[0]['start']=0.2;return {'segments':segments}
        wx=types.SimpleNamespace(load_align_model=lambda **kw:(model,{}),align=align)
        with patch.dict(sys.modules,{'torch':types.SimpleNamespace(uint8=object())}):result,status=align_result(wx,raw,None,'uk','keep_asr',lambda state:None)
        self.assertEqual(raw,before);self.assertEqual(result['segments'][0]['start'],0.2);self.assertEqual(status['status'],'COMPLETED_UNREVIEWED');self.assertTrue(status['model']['weights_sha256'])
    def test_normalize_original_offset_and_missing_word_time(self):
        raw=[{'start':0.1,'end':1.2,'text':'SYNTHETIC','words':[{'word':'test'}]}]
        segment=normalize(raw,61000000,62000000,'ALIGNED_UNREVIEWED')[0]
        self.assertEqual(segment['start_us'],61100000);self.assertEqual(segment['end_us'],62000000)
        self.assertIn('WORD_TIME_MISSING',segment['review_flags']);self.assertIn('END_CLIPPED_TO_WINDOW',segment['review_flags']);self.assertNotIn('start_us',segment['words'][0])
    def test_anomalies_are_flagged_without_changing_times(self):
        raw=[{'start':3.116,'end':9.286,'text':'Кажи.','words':[{'word':'Кажи.','start':3.116,'end':9.286,'score':0.972}]}]
        u=normalize(raw,0,60000000,'ALIGNED_UNREVIEWED')[0]
        self.assertEqual((u['words'][0]['start_us'],u['words'][0]['end_us']),(3116000,9286000))
        self.assertIn('WORD_DURATION_LONG',u['words'][0]['review_flags'])
        self.assertIn('WORD_DURATION_LONG',u['review_flags'])
    def test_low_score_and_window_edge_use_original_offset(self):
        raw=[{'start':0.1,'end':1,'text':'test','words':[{'word':'test','start':0.8,'end':1,'score':0.181}]}]
        w=normalize(raw,61000000,62000000,'ALIGNED_UNREVIEWED')[0]['words'][0]
        self.assertIn('WORD_NEAR_WINDOW_EDGE',w['review_flags']);self.assertIn('ALIGNMENT_SCORE_LOW',w['review_flags'])
    def test_normal_word_has_no_specific_warning(self):
        raw=[{'start':1,'end':1.5,'text':'test','words':[{'word':'test','start':1,'end':1.5,'score':0.9}]}]
        self.assertEqual(normalize(raw,0,60000000,'ALIGNED_UNREVIEWED')[0]['words'][0]['review_flags'],[])
    def test_empty_channel_skips_alignment_with_explicit_status(self):
        result,status=align_result(None,{'segments':[]},None,'uk','require',lambda state:None)
        self.assertEqual(status['status'],'NOT_APPLICABLE_EMPTY')

if __name__=='__main__':unittest.main()
