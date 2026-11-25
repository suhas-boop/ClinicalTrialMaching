"""Screen a compiled TrialGPT study against a supplied normalized patient packet or rerun after new evidence."""
import argparse,json
from pathlib import Path
from run import HERE,fingerprint
from evidence_review import screen
from record_search import connect,retrieve
from contextlib import closing

def execute(study,packet,criterion=None,index=None):
    import sys
    sys.path.insert(0,str(HERE.parent/'round11'))
    from catalog import verify
    pack=verify(json.loads((HERE.parent/'round11/compiled.json').read_text()))
    entries={k:{name:e[name] for name in ('rule','source')} for k,e in pack['rules'].items()}
    selected={k:e for k,e in entries.items() if e['source']['trial_id']==study}
    if not selected:raise ValueError('Unknown study')
    version=fingerprint(selected)
    if criterion and criterion not in selected:raise ValueError('Criterion belongs to a different study')
    rules={k:e['rule'] for k,e in selected.items() if not criterion or k==criterion}
    if index:
        if not Path(index).is_file():raise ValueError('Missing evidence archive index')
        with closing(connect(index)) as db:return retrieve(db,rules,packet,study,version)
    return screen(rules,packet,study,version)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--study',required=True);p.add_argument('--packet',type=Path,required=True)
    p.add_argument('--criterion');p.add_argument('--index',help='Optional local index created by pocketmd.py records')
    args=p.parse_args();print(json.dumps(execute(args.study,json.loads(args.packet.read_text()),args.criterion,args.index),indent=2))
