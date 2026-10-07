"""Headless checks of GUI state handling; no Tk window or ASR model is started."""
import ast,queue,time,unittest
from pathlib import Path
from unittest.mock import Mock

class Value:
    def __init__(self,value=None):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value

class ASRUIStateTests(unittest.TestCase):
    def load(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'Start_ASR.py').read_text())
        funcs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('update_scope','poll','tick')]
        ns={'queue':queue,'time':time,'json':__import__('json'),'short':Value(False),'busy':False,'start_entry':Mock(),'end_entry':Mock(),'scope_hint':Value(),'root':Mock(),'events':queue.Queue(),'last_event':None,'stage_at':0,'started_at':time.monotonic(),'STAGES':{},'cancel':Mock(),'status':Value(),'activity':Value(),'log':Mock(),'bar':Mock(),'start_button':Mock(),'short_button':Mock(),'stop_button':Mock(),'messagebox':Mock()}
        ns['cancel'].is_set.return_value=False
        exec(compile(ast.Module(body=funcs,type_ignores=[]),'Start_ASR.py','exec'),ns)
        return ns
    def test_full_file_disables_time_fields(self):
        n=self.load();n['update_scope']();n['start_entry'].configure.assert_called_with(state='disabled');self.assertIn('ігноруються',n['scope_hint'].get())
        n['short'].set(True);n['update_scope']();n['end_entry'].configure.assert_called_with(state='normal')
    def test_repeated_process_heartbeat_does_not_reset_stage_timer(self):
        n=self.load();n['busy']=True
        event=('progress',{'state':'ASR_RUNNING','role':'respondent','pid':123,'process_alive':True})
        n['events'].put(event);n['poll']();first=n['stage_at']
        n['events'].put(event);n['poll']();self.assertEqual(n['stage_at'],first);self.assertIn('PID 123',n['status'].get())
    def test_completion_stops_indicator_and_unlocks_start(self):
        n=self.load();n['busy']=True;n['events'].put(('done',{'review_files':['sample.txt'],'warnings':[]}));n['poll']()
        self.assertFalse(n['busy']);n['bar'].stop.assert_called_once();n['start_button'].configure.assert_called_with(state='normal');self.assertEqual(n['last_text'],'sample.txt')
    def test_error_stops_indicator(self):
        n=self.load();n['busy']=True;n['events'].put(('error','test failure'));n['poll']();self.assertFalse(n['busy']);n['bar'].stop.assert_called_once();n['messagebox'].showerror.assert_called_once()
