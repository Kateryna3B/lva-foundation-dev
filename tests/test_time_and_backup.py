import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lva_system.time_input import parse_time_ms,format_time,boundaries_from_times
from lva_system.backup_check import verify_backup
from lva_system.core import Store,digest
from test_foundation import wav,form

class TimeInputTests(unittest.TestCase):
    def test_real_pilot_boundary_and_separator(self):
        for value in ('16:10.400','16:10,400'):
            bounds,meta=boundaries_from_times([value],21309000,11025,2)
            self.assertEqual(bounds,[0,10698660,21309000]);self.assertEqual(meta['requested_internal_times'],[value])
    def test_notation_and_rounding(self):
        self.assertEqual(parse_time_ms('16:10'),970000);self.assertEqual(parse_time_ms('0:01.2'),1200)
        bounds,_=boundaries_from_times(['00:00.001'],100,500,2);self.assertEqual(bounds,[0,1,100])
        bounds,_=boundaries_from_times(['00:00.001'],100,11025,2);self.assertEqual(bounds,[0,11,100])
    def test_invalid_time_and_boundaries(self):
        for s in ('16:60','16.10','-1:10','NaN','16:10.4000','00:01:30','16:10e3','16:10x','١٦:١٠'):
            with self.subTest(s=s),self.assertRaises(ValueError):parse_time_ms(s)
        for values in ([],['00:00'],['00:10'],['00:11'],['00:01','00:02']):
            with self.subTest(values=values),self.assertRaises(ValueError):boundaries_from_times(values,100,10,2)
        for values in (['00:02','00:01'],['00:01','00:01']):
            with self.assertRaises(ValueError):boundaries_from_times(values,100,10,3)
    def test_exact_end_and_one_part(self):
        bounds,_=boundaries_from_times([],21309000,11025,1);self.assertEqual(bounds,[0,21309000])
        self.assertEqual(format_time(21309000,11025),'32:12.789')
        self.assertEqual(format_time(10698660,11025),'16:10.400')
    def test_frame_collapse_blocked(self):
        with self.assertRaises(ValueError):boundaries_from_times(['00:00.001'],100,10,2)
        with self.assertRaises(ValueError):boundaries_from_times(['00:01.001','00:01.002'],100,10,3)

class IntegratedTimeBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name);self.wav=self.p/'input.wav';wav(self.wav,frames=12601,rate=10)
        self.form=self.p/'input.xlsx';form(self.form);self.st=Store(self.p/'store');self.cid=self.st.register(self.form,self.wav)['case_id'];self.st.prepare(self.cid,2)
    def tearDown(self):self.st.close();self.tmp.cleanup()
    def test_time_parts_and_unchanged_legacy_parts(self):
        self.assertEqual(self.st.parts_plan(self.cid)['part_count'],2)
        self.st.parts_at_times(self.cid,['10:00.123']);parts=self.st.files(self.cid,'part')
        meta=json.loads(parts[0]['metadata']);self.assertEqual(meta['end_frame'],6001);self.assertEqual(meta['time_input']['requested_internal_ms'],[600123])
        before=self.st.files(self.cid);plan=self.st.parts_plan(self.cid);self.assertEqual(len(plan['existing_parts']),2)
        with self.assertRaises(ValueError):self.st.parts_at_times(self.cid,['10:00.124'])
        self.assertEqual(before,self.st.files(self.cid));self.assertFalse(self.st.verify(self.cid)['issues'])
    def test_legacy_frame_metadata_supported(self):
        self.st.parts(self.cid,[0,6300,12601]);plan=self.st.parts_plan(self.cid)
        self.assertEqual(plan['existing_parts'][0]['end'],'10:30.000');self.assertFalse('time_input' in json.loads(self.st.files(self.cid,'part')[0]['metadata']))
    def test_backup_success_missing_and_corrupt_without_mutation(self):
        b=self.st.backup(self.p/'backup');folder=Path(b['backup_path']);registry=folder/'registry.sqlite3';before=registry.read_bytes()
        self.assertEqual(verify_backup(folder),{'checked_files':5,'issues':[]});self.assertEqual(before,registry.read_bytes())
        r=self.st.files(self.cid,'original')[0];target=folder/r['path'];target.write_bytes(b'bad');self.assertEqual(verify_backup(folder)['issues'][0]['issue'],'HASH_MISMATCH')
        target.unlink();self.assertEqual(verify_backup(folder)['issues'][0]['issue'],'MISSING')
    def test_incomplete_and_unsafe_backup_rejected(self):
        folder=self.p/'incomplete';folder.mkdir()
        with self.assertRaises(ValueError):verify_backup(folder)
        marker=folder/'COMPLETE.json'
        marker.write_text(json.dumps({'schema_version':'1.0','checksums':{'registry.sqlite3':'0'*64,'../outside':'0'*64}}))
        with self.assertRaises(ValueError):verify_backup(folder)

if __name__=='__main__':unittest.main()
