"""Read-only verification of completed backups; never opens SQLite."""
import json
from pathlib import Path,PurePosixPath
from .core import digest

def verify_backup(folder):
    root=Path(folder).resolve();marker=root/'COMPLETE.json'
    if not marker.is_file():raise ValueError('Немає COMPLETE.json: завершення резервування не підтверджене')
    if marker.stat().st_size>16*1024*1024:raise ValueError('Надто великий опис резервної копії')
    manifest=json.loads(marker.read_text(encoding='utf-8'))
    checks=manifest.get('checksums')
    if manifest.get('schema_version')!='1.0' or not isinstance(checks,dict) or not checks or 'registry.sqlite3' not in checks:raise ValueError('Невідомий або неповний опис резервної копії')
    issues=[]
    for name,expected in checks.items():
        if not isinstance(name,str) or '\\' in name or ':' in name or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts:raise ValueError('Недопустимий шлях у резервній копії')
        if not isinstance(expected,str) or len(expected)!=64 or any(c not in '0123456789abcdef' for c in expected):raise ValueError('Некоректний SHA-256 у резервній копії')
        target=(root/name).resolve()
        if root not in target.parents:raise ValueError('Шлях виходить за межі резервної копії')
        if not target.is_file():issues.append({'file':name,'issue':'MISSING'})
        elif digest(target)!=expected:issues.append({'file':name,'issue':'HASH_MISMATCH'})
    return {'checked_files':len(checks),'issues':issues}
