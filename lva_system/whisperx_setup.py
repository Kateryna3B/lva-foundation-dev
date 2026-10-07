"""Locate and hash cached reference weights using the user's existing Python."""
import json,os,subprocess
from pathlib import Path

def prepare_existing(python,descriptor):
    result=subprocess.run([str(python),'-m','lva_system.whisperx_worker','--prepare',str(descriptor)],
                          cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,encoding='utf-8',
                          timeout=180,env={**os.environ,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'})
    if result.returncode:raise ValueError('Наявний WhisperX або кеш моделі не готовий; пакети не встановлювалися. '+result.stderr[-2000:])
    data=json.loads(result.stdout)
    if data.get('status')!='LOCAL_REFERENCE_READY':raise ValueError('Невідомий результат підготовки WhisperX')
    return data
