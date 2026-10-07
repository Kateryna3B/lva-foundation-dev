"""Explicit local Windows DLL directories, applied before importing GPU runtime."""
import os
from pathlib import Path
_HANDLES=[]
def configure(directories):
    if os.name!='nt':return
    for directory in directories:
        p=Path(directory).resolve()
        if not p.is_dir():raise ValueError('Немає каталогу CUDA/cuDNN: '+str(p))
        os.environ['PATH']=str(p)+os.pathsep+os.environ.get('PATH','')
        _HANDLES.append(os.add_dll_directory(str(p)))
