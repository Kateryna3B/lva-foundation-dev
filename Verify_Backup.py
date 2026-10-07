"""Read-only backup checksum checker; does not open or mutate SQLite."""
import sys,json
from lva_system.backup_check import verify_backup

def main():
    if len(sys.argv)!=2:
        print('Usage: py -3 Verify_Backup.py "E:\\Backups\\backup_UUID"');return 1
    try:
        result=verify_backup(sys.argv[1]);print(json.dumps(result,ensure_ascii=False,indent=2));return 2 if result['issues'] else 0
    except Exception as e:
        print(json.dumps({'error':str(e)},ensure_ascii=False));return 1
if __name__=='__main__':sys.exit(main())
