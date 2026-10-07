"""Actual local model + one-second synthetic silence smoke test; no private audio."""
import ctypes,json,os,tempfile,sys,wave
from pathlib import Path
from lva_system.asr import model_identity,inspect_engine
from lva_system.asr_worker import transcribe
from lva_system.asr_runtime import configure

def main():
    base=Path(__file__).resolve().parent;settings=json.loads((base/'ASR_SETTINGS.json').read_text(encoding='utf-8'));device=settings['device']
    if device not in ('cuda','cpu'):raise ValueError('Unknown device')
    configure(settings.get('dll_dirs',[]))
    if device=='cuda' and os.name=='nt':
        for library in ['cublas64_12.dll','cudnn64_9.dll']:
            try:ctypes.WinDLL(library)
            except OSError as e:raise RuntimeError('Не завантажено '+library+'. Для GPU потрібні CUDA 12/cuDNN 9 та їхні bin-каталоги у PATH або dll_dirs в ASR_SETTINGS.json.') from e
    import ctranslate2
    compute='int8_float16' if device=='cuda' else 'int8'
    supported=sorted(ctranslate2.get_supported_compute_types(device))
    if compute not in supported:raise ValueError('Compute type unsupported: '+compute)
    model=base/'models'/'large-v3';identity=model_identity(model)
    with tempfile.TemporaryDirectory() as directory:
        p=Path(directory);wav=p/'silence.wav'
        with wave.open(str(wav),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\0'*32000)
        transcribe({'model_path':str(model),'audio_path':str(wav),'device':device,'compute_type':compute,'language':'uk','role':'probe','request_fingerprint':'synthetic_probe','output_path':str(p/'out.json'),'progress_path':str(p/'progress.json'),'dll_dirs':settings.get('dll_dirs',[])})
    print(json.dumps({'status':'ENGINE_SMOKE_TEST_PASSED','device':device,'compute_type':compute,'supported_compute_types':supported,'model':identity,'engine_versions':inspect_engine(sys.executable),'quality_tested':False},ensure_ascii=False,indent=2))
if __name__=='__main__':
    try:main()
    except Exception as e:print(json.dumps({'status':'NOT_READY','error':str(e)},ensure_ascii=False,indent=2));sys.exit(1)
