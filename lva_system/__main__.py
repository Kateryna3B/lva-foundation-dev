import argparse,json,sys
from pathlib import Path
# Offline, vendored IANA database; no downloads or installations at runtime.
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'vendor'))
from .core import Store

def main():
    p=argparse.ArgumentParser(description='LVA Foundation 0.2.1 — локальний пілот')
    p.add_argument('--root',required=True,help='Локальний робочий каталог');s=p.add_subparsers(dest='command',required=True)
    s.add_parser('init');s.add_parser('list');s.add_parser('people');s.add_parser('recover')
    q=s.add_parser('intake');q.add_argument('--form',required=True);q.add_argument('--audio',required=True);q.add_argument('--allow-new-case',action='store_true')
    q=s.add_parser('prepare');q.add_argument('--case',required=True);q.add_argument('--respondent-channel',type=int,choices=[1,2],required=True)
    q=s.add_parser('parts');q.add_argument('--case',required=True)
    g=q.add_mutually_exclusive_group(required=True);g.add_argument('--boundaries',type=int,nargs='+',help='Сумісний технічний режим кадрів');g.add_argument('--times',nargs='*',help='Лише внутрішні межі MM:SS.mmm')
    q=s.add_parser('parts-plan');q.add_argument('--case',required=True)
    q=s.add_parser('verify');q.add_argument('--case',required=True)
    q=s.add_parser('import-lva');q.add_argument('--case',required=True);q.add_argument('--input',required=True);q.add_argument('--csv',required=True);q.add_argument('--part-id');q.add_argument('--legacy-full',action='store_true')
    q=s.add_parser('backup');q.add_argument('--destination',required=True)
    args=p.parse_args();store=None
    try:
        store=Store(args.root)
        if args.command=='init':result={'root':str(store.root),'schema_version':1}
        elif args.command=='list':result=[dict(r) for r in store.db.execute('SELECT id,code FROM cases ORDER BY rowid')]
        elif args.command=='people':result=[dict(r) for r in store.db.execute('SELECT id,alias FROM people ORDER BY rowid')]
        elif args.command=='intake':result=store.register(args.form,args.audio,args.allow_new_case)
        elif args.command=='prepare':result=store.prepare(args.case,args.respondent_channel)
        elif args.command=='parts':result=store.parts_at_times(args.case,args.times) if args.times is not None else store.parts(args.case,args.boundaries)
        elif args.command=='parts-plan':result=store.parts_plan(args.case)
        elif args.command=='import-lva':result=store.import_lva(args.case,args.input,args.csv,args.part_id,args.legacy_full)
        elif args.command=='verify':result=store.verify(args.case)
        elif args.command=='recover':result=store.recover()
        elif args.command=='backup':result=store.backup(args.destination)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if args.command=='verify' and result['issues']:return 2
        return 0
    except Exception as e:
        print(json.dumps({'error':str(e)},ensure_ascii=False),file=sys.stderr);return 1
    finally:
        if store:store.close()
if __name__=='__main__':sys.exit(main())
