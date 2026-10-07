"""Offline subprocess engine. Reads registered mono, writes only staging outputs."""
import argparse,json,os,sys,math,importlib.metadata
from pathlib import Path
from decimal import Decimal,ROUND_HALF_UP
from .core import uid,dump
from . import audio

def atomic(path,data):
    path=Path(path);tmp=path.with_suffix('.tmp')
    with tmp.open('w',encoding='utf-8') as f:f.write(json.dumps(data,ensure_ascii=False,sort_keys=True,allow_nan=False));f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)
def versions():
    return {name:importlib.metadata.version(name) for name in ['faster-whisper','ctranslate2','av','numpy']}
def microseconds(value):
    if not math.isfinite(value):raise ValueError('ASR returned nonfinite time')
    return int((Decimal(str(value))*1000000).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
def transcribe(request):
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1';os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
    info=audio.inspect(request['audio_path'])
    if info['channels']!=1:raise ValueError('ASR input must be mono')
    from .asr_runtime import configure
    configure(request.get('dll_dirs',[]))
    from faster_whisper import WhisperModel
    model=WhisperModel(request['model_path'],device=request['device'],compute_type=request['compute_type'],local_files_only=True,num_workers=1,cpu_threads=4)
    segments,detected=model.transcribe(request['audio_path'],language=request['language'],task='transcribe',beam_size=5,temperature=0.0,word_timestamps=True,vad_filter=False,condition_on_previous_text=True)
    out=[];duration=info['frames']*1000000//info['sample_rate']
    for index,s in enumerate(segments):
        raw_a=microseconds(s.start);raw_b=microseconds(s.end)
        if raw_a<0 or raw_b<=raw_a or raw_a>=duration:raise ValueError('ASR returned invalid segment interval')
        flags=[]
        if raw_b>duration:flags.append('END_CLIPPED_TO_AUDIO')
        b=min(raw_b,duration);words=[]
        for w in s.words or []:
            wa=microseconds(w.start);wb=microseconds(w.end)
            if wb<wa or not math.isfinite(w.probability):raise ValueError('ASR returned invalid word')
            words.append({'word':w.word,'start_us':wa,'end_us':wb,'probability':w.probability})
        metrics={'avg_logprob':s.avg_logprob,'no_speech_probability':s.no_speech_prob}
        if any(not math.isfinite(v) for v in metrics.values()):raise ValueError('ASR returned nonfinite metric')
        out.append({'utterance_id':uid(),'source_segment_index':index,'text':s.text,'start_us':raw_a,'end_us':b,'raw_asr_start_us':raw_a,'raw_asr_end_us':raw_b,'words':words,'metrics':metrics,'review_flags':flags,'status':'DRAFT_UNREVIEWED'})
        atomic(request['progress_path'],{'segments':len(out),'processed_us':b,'state':'RUNNING'})
    payload={'schema_version':'1.0','request_fingerprint':request['request_fingerprint'],'role':request['role'],'duration_us':duration,'detected_language':detected.language,'language_probability':detected.language_probability,'engine_versions':versions(),'segments':out,'status':'DRAFT_UNREVIEWED'}
    atomic(request['output_path'],payload);atomic(request['progress_path'],{'segments':len(out),'processed_us':duration,'state':'DONE'})
def main():
    p=argparse.ArgumentParser();p.add_argument('--describe',action='store_true');p.add_argument('--request');a=p.parse_args()
    if a.describe:print(json.dumps(versions()));return
    if not a.request:p.error('request required')
    transcribe(json.loads(Path(a.request).read_text(encoding='utf-8')))
if __name__=='__main__':main()
