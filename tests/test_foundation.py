import sys,tempfile,unittest,struct,zipfile,json,hashlib
from pathlib import Path
from xml.etree import ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lva_system import audio,intake,lva_csv
from lva_system.core import Store,digest

BASE=Path(__file__).resolve().parents[1]
N='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
def form(path,updates=None):
    vals=dict(requester_mode='new',requester_alias='Same',respondent_mode='new',respondent_alias='Same',conversation_date='2026-09-28',conversation_time='12:30:00',timezone='Europe/Kyiv',received_date='2026-09-28',channel_scheme='interviewer_1_respondent_2',topic1='Synthetic')
    vals.update(updates or {})
    with zipfile.ZipFile(BASE/'templates'/'Intake_v1.xlsx') as src,zipfile.ZipFile(path,'w') as dst:
        for name in src.namelist():
            data=src.read(name)
            if name=='xl/worksheets/sheet1.xml':
                root=ET.fromstring(data)
                for index,key in enumerate(intake.FIELDS,6):
                    row=root.find(f'.//{{{N}}}row[@r="{index}"]')
                    for c in list(row):
                        if c.attrib.get('r')=='C'+str(index):row.remove(c)
                    if key in vals and vals[key] is not None:
                        c=ET.SubElement(row,'{'+N+'}c',r='C'+str(index),t='inlineStr');is_=ET.SubElement(c,'{'+N+'}is');ET.SubElement(is_,'{'+N+'}t').text=str(vals[key])
                data=ET.tostring(root,encoding='utf-8',xml_declaration=True)
            dst.writestr(name,data)
def wav(path,bits=16,tag=1,frames=31,channels=2,rate=10):
    width=bits//8
    fmt=struct.pack('<HHIIHH',tag,channels,rate,rate*channels*width,channels*width,bits)
    samples=[(i%127).to_bytes(width,'little') for i in range(frames*channels)]
    payload=b''.join(samples);body=b'WAVEfmt '+struct.pack('<I',len(fmt))+fmt+b'data'+struct.pack('<I',len(payload))+payload+(b'\0' if len(payload)%2 else b'')
    path.write_bytes(b'RIFF'+struct.pack('<I',len(body))+body);return payload
class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name);self.a=self.p/'source.wav';wav(self.a);self.f=self.p/'form.xlsx';form(self.f);self.st=Store(self.p/'store')
    def tearDown(self):self.st.close();self.tmp.cleanup()
    def reg(self):return self.st.register(self.f,self.a)['case_id']
    def test_form_native_template(self):
        self.assertEqual(intake.read_form(self.f)['started_at_utc'],'2026-09-28T09:30:00+00:00')
        with zipfile.ZipFile(BASE/'templates'/'Intake_v1.xlsx') as z:
            sheet=ET.fromstring(z.read('xl/worksheets/sheet1.xml'));self.assertEqual(len(sheet.findall('.//{'+N+'}dataValidation')),4)
    def test_dst_ambiguity_and_gap(self):
        d=intake.read_form(self.f);d.update(conversation_date='2026-10-25',conversation_time='03:30:00',received_date='2026-10-25')
        with self.assertRaises(ValueError):intake.validate(d)
        d['utc_offset_minutes']='180';self.assertIn('+03:00',intake.validate(d)['started_at_local'])
        d.update(conversation_date='2026-03-29',received_date='2026-03-29',conversation_time='03:30:00',utc_offset_minutes=None)
        with self.assertRaises(ValueError):intake.validate(d)
    def test_exact_channels_formats(self):
        for bits,tag in [(16,1),(24,1),(32,1),(32,3),(64,3)]:
            p=self.p/f'{bits}_{tag}.wav';raw=wav(p,bits,tag);out=self.p/f'{bits}_{tag}_mono.wav';meta=audio.write_channel(p,out,2)
            width=bits//8;expected=b''.join(raw[i+width:i+2*width] for i in range(0,len(raw),2*width));info=audio.inspect(out)
            with out.open('rb') as f:f.seek(info['data_offset']);self.assertEqual(f.read(info['data_bytes']),expected)
            self.assertEqual(meta['frames'],31)
    def test_truncated_rejected(self):
        self.a.write_bytes(self.a.read_bytes()[:-1])
        with self.assertRaises(ValueError):audio.inspect(self.a)
    def test_duration_rules(self):
        self.assertEqual(audio.count_parts(1200,1),1);self.assertEqual(audio.count_parts(1201,1),2);self.assertEqual(audio.count_parts(2700,1),3);self.assertEqual(audio.count_parts(3600,1),3)
        with self.assertRaises(ValueError):audio.count_parts(3601,1)
        self.assertEqual(audio.equal_boundaries(2701,1),[0,900,1800,2701])
    def test_duplicate_and_alias_identity(self):
        cid=self.reg();self.assertTrue(self.st.register(self.f,self.a)['reused']);people=self.st.db.execute('SELECT * FROM people').fetchall();self.assertEqual(len(people),2);self.assertNotEqual(people[0]['id'],people[1]['id']);self.assertEqual(digest(self.a),self.st.case(cid)['source_hash'])
        form(self.f,{'topic1':'Other'})
        with self.assertRaises(ValueError):self.reg()
    def test_parts_and_backup_restore(self):
        cid=self.reg();self.st.prepare(cid,2);self.assertTrue(self.st.prepare(cid,2)['reused']);self.st.parts(cid,[0,31]);self.assertFalse(self.st.verify(cid)['issues'])
        b=self.st.backup(self.p/'backups');copy=Store(b['backup_path'])
        try:self.assertFalse(copy.verify(cid)['issues']);self.assertEqual(copy.case(cid)['id'],cid)
        finally:copy.close()
    def test_bad_boundaries(self):
        cid=self.reg();self.st.prepare(cid,2)
        for bounds in ([0,30],[1,31],[0,10,31],[0,31.0]):
            with self.assertRaises(ValueError):self.st.parts(cid,bounds)
    def test_corruption_blocks(self):
        cid=self.reg();p=self.st.root/self.st.files(cid,'original')[0]['path'];p.write_bytes(p.read_bytes()+b'x');self.assertEqual(self.st.verify(cid)['issues'][0]['issue'],'HASH_MISMATCH')
        with self.assertRaises(ValueError):self.st.prepare(cid,2)
    def test_recovery_at_three_phases(self):
        for phase in ('prepared','promoted','committed'):
            other=Store(self.p/phase)
            def fault(p):
                if p==phase:raise RuntimeError('simulated interruption')
            other.fault=fault
            with self.assertRaises(RuntimeError):other.register(self.f,self.a)
            other.close();other=Store(self.p/phase)
            try:
                other.recover();rows=other.db.execute('SELECT id FROM cases').fetchall();self.assertEqual(len(rows),1);self.assertFalse(other.verify(rows[0]['id'])['issues']);self.assertTrue((other.root/'cases'/rows[0]['id']/'manifest.json').exists())
            finally:other.close()
    def test_writer_exclusion(self):
        other=Store(self.st.root)
        try:
            with self.st.locked():
                with self.assertRaises(RuntimeError):
                    with other.locked():pass
        finally:other.close()
    def test_csv_raw_missing_negative_and_import(self):
        import csv,io
        buf=io.StringIO();writer=csv.writer(buf);writer.writerow(lva_csv.HEADER+['']);writer.writerow(['001','Pn','S 00:00:001','E 00:01:002','*']+['-273','0','']+['1']*18)
        raw=buf.getvalue().encode();parsed=lva_csv.parse(raw);m=parsed['segments'][0]['metrics'];self.assertEqual(m[0]['parsed_number'],-273);self.assertEqual(m[1]['parsed_number'],0);self.assertEqual(m[2]['value_state'],'missing')
        cid=self.reg();mono=self.p/'processed.wav';wav(mono,channels=1);csvpath=self.p/'export.csv';csvpath.write_bytes(raw)
        result=self.st.import_lva(cid,mono,csvpath,legacy_full=True);self.assertEqual(result['time_status'],'UNVERIFIED');self.assertEqual(result['segment_count'],1)
    def test_three_part_payload_reassembles(self):
        raw=wav(self.a,frames=2701,rate=1);cid=self.reg();self.st.prepare(cid,2);self.st.parts(cid,[0,900,1800,2701]);joined=b''
        for r in self.st.files(cid,'part'):
            p=self.st.root/r['path'];info=audio.inspect(p)
            with p.open('rb') as f:f.seek(info['data_offset']);joined+=f.read(info['data_bytes'])
        self.assertEqual(joined,b''.join(raw[i+2:i+4] for i in range(0,len(raw),4)))
    def test_extensible_pcm_channel(self):
        base=struct.pack('<HHIIHH',65534,2,10,40,4,16)
        fmt=base+struct.pack('<HHI',22,16,3)+struct.pack('<I',1)+bytes.fromhex('00001000800000aa00389b71')
        payload=struct.pack('<hhhh',1,-1,2,-2);body=b'WAVEfmt '+struct.pack('<I',len(fmt))+fmt+b'data'+struct.pack('<I',len(payload))+payload
        self.a.write_bytes(b'RIFF'+struct.pack('<I',len(body))+body);p=self.p/'ext.wav';info=audio.write_channel(self.a,p,2)
        self.assertEqual(info['frames'],2)
        with p.open('rb') as f:f.seek(info['data_offset']);self.assertEqual(f.read(info['data_bytes']),struct.pack('<hh',-1,-2))
    def test_mixed_and_long_routes_block(self):
        form(self.f,{'channel_scheme':'mixed'});cid=self.reg()
        with self.assertRaises(ValueError):self.st.prepare(cid,2)
        wav(self.a,frames=3601,rate=1);form(self.f);cid=self.reg()
        self.assertEqual(json.loads(self.st.case(cid)['data'])['stage'],'DURATION_REVIEW_REQUIRED')
        with self.assertRaises(ValueError):self.st.prepare(cid,2)
    def test_timezone_database_offline(self):
        import zoneinfo
        old=zoneinfo.TZPATH;zoneinfo.reset_tzpath([]);zoneinfo.ZoneInfo.clear_cache()
        try:self.assertEqual(intake.read_form(self.f)['started_at_utc'],'2026-09-28T09:30:00+00:00')
        finally:zoneinfo.reset_tzpath(old);zoneinfo.ZoneInfo.clear_cache()
    def test_wrong_csv_schema(self):
        with self.assertRaises(ValueError):lva_csv.parse(b'No.,Other\n1,2\n')
    def test_alias_error_identifies_requester_cell(self):
        form(self.f,{'requester_alias':'Test1','respondent_alias':'NewResp'})
        with self.assertRaisesRegex(ValueError,r'Intake!C8.*requester_alias.*U\+0031'):
            intake.read_form(self.f)
        self.assertEqual(self.st.db.execute('SELECT count(*) FROM cases').fetchone()[0],0)
    def test_alias_error_identifies_respondent_character(self):
        form(self.f,{'respondent_alias':'NеwResp'})  # Cyrillic е at position 2.
        with self.assertRaisesRegex(ValueError,r'Intake!C12.*respondent_alias.*позиції 2.*U\+0435'):
            intake.read_form(self.f)
    def test_valid_visible_alias_and_missing_alias(self):
        form(self.f,{'respondent_alias':'NewResp'})
        self.assertEqual(intake.read_form(self.f)['respondent_alias'],'NewResp')
        form(self.f,{'requester_alias':None})
        with self.assertRaisesRegex(ValueError,r'Intake!C8.*поле порожнє'):
            intake.read_form(self.f)
if __name__=='__main__':unittest.main()
