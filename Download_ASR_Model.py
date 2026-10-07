"""Explicit online provisioning only. Runtime ASR never invokes this script."""
import json,os,sys
from pathlib import Path
from huggingface_hub import HfApi,snapshot_download
from lva_system.core import digest,dump
from lva_system.asr_worker import atomic
from lva_system.asr import model_identity

def main():
    root=Path(__file__).resolve().parent/'models'/'large-v3'
    if (root/'MODEL_MANIFEST.json').exists():
        print(json.dumps({'status':'MODEL_ALREADY_VERIFIED','identity':model_identity(root)},indent=2));return
    repo='Systran/faster-whisper-large-v3';revision=HfApi().model_info(repo).sha
    print('Downloading model weights from '+repo+' at revision '+revision,flush=True)
    snapshot_download(repo_id=repo,revision=revision,local_dir=str(root),allow_patterns=['model.bin','config.json','tokenizer.json','preprocessor_config.json','vocabulary.*','README.md','LICENSE*'])
    files={f.name:digest(f) for f in root.iterdir() if f.is_file() and f.name!='MODEL_MANIFEST.json'}
    for required in ['model.bin','config.json','tokenizer.json']:
        if required not in files:raise ValueError('Download incomplete: '+required)
    atomic(root/'MODEL_MANIFEST.json',{'schema_version':'1.0','repo_id':repo,'revision':revision,'files':files})
    print(json.dumps({'status':'MODEL_VERIFIED','identity':model_identity(root)},indent=2))
if __name__=='__main__':main()
