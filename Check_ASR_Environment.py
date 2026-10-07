"""Local read-only ASR environment inventory; no audio, user paths or network."""
import ctypes,importlib.metadata,json,platform,shutil,subprocess,sys

def collect():
    report={'schema_version':'1.0','python_version':platform.python_version(),'python_bits':ctypes.sizeof(ctypes.c_void_p)*8,'os':platform.system(),'ram_bytes':None,'nvidia_gpus':[],'packages':{},'notes':[],'scope':'ENVIRONMENT_ONLY_NOT_ASR_EXECUTION'}
    if sys.platform=='win32':
        class Memory(ctypes.Structure):
            _fields_=[('length',ctypes.c_uint32),('load',ctypes.c_uint32)]+[(n,ctypes.c_uint64) for n in ('total_physical','available_physical','total_page','available_page','total_virtual','available_virtual','reserved')]
        memory=Memory();memory.length=ctypes.sizeof(memory)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):report['ram_bytes']=memory.total_physical
        else:report['notes'].append('RAM query failed')
    for package in ['faster-whisper','ctranslate2','av','torch','numpy']:
        try:report['packages'][package]=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:report['packages'][package]='NOT_INSTALLED'
    executable=shutil.which('nvidia-smi')
    if executable:
        try:
            r=subprocess.run([executable,'--query-gpu=name,memory.total,driver_version','--format=csv,noheader,nounits'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=10,check=True)
            import csv,io
            for row in csv.reader(io.StringIO(r.stdout)):
                if len(row)!=3:report['notes'].append('Unexpected GPU response');continue
                name,memory,driver=[v.strip() for v in row]
                report['nvidia_gpus'].append({'name':name,'memory_mib':int(memory) if memory.isdigit() else None,'driver_version':driver})
        except (subprocess.SubprocessError,OSError):report['notes'].append('NVIDIA query failed; GPU readiness not established')
    else:report['notes'].append('nvidia-smi unavailable; this does not establish absence of a GPU')
    report['notes'].append('CUDA libraries, model files and real transcription are not tested by this inventory')
    return report
if __name__=='__main__':print(json.dumps(collect(),ensure_ascii=False,indent=2))
