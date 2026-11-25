"""Screen a single FHIR chart, or replay all assigned pairs with the same entry point."""
import argparse
import csv
import json
from collections import Counter
from contextlib import closing
from pathlib import Path
from catalog import HERE,R9,verify
from chart import open_chart,search
from native import NativeChart
from evidence_review import screen_snapshot
from run import fingerprint

def read_json(path):
    return json.loads(Path(path).read_text())

def write_json(path, data):
    path.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')

def screen(resources,subject,pack,study,criterion=None):
    entries={k:e for k,e in pack['rules'].items() if e['source']['trial_id']==study}
    if not entries or (criterion is not None and criterion not in entries):
        raise ValueError('Unknown study or criterion')
    version=fingerprint({k:{name:e[name] for name in ('rule','source')} for k,e in entries.items()})
    selected={k:e for k,e in entries.items() if criterion is None or k==criterion}
    bindings={cid:pack['contracts'][cid] for e in selected.values() for cid in e['bindings'].values()}
    snap=NativeChart(resources,subject,bindings)
    ctx=dict(patient=subject,episode='benchmark presentation',encounter='benchmark vignette',as_of=snap.hash,
             source_scope='multiple_subjects' if subject.startswith('Group/') else 'individual',source_sha256=snap.hash)
    out=screen_snapshot({k:e['rule'] for k,e in selected.items()},snap,ctx,study,version)
    for k,v in out['criteria'].items():
        for name,f in v['facts'].items():f['contract']=selected[k]['bindings'][name]
        v['source_sentences']=sorted({n for ref in v['evidence'] for n in snap.refs[ref]})
    out.update(catalog_sha256=pack['sha256'],source_sha256=snap.hash)
    return out

def replay(export,out,pack):
    assignments=read_json(R9/'assignments.json')
    subjects={r['case']:r['subject'] for r in read_json(export/'cases.json')}
    if {str(row['annotation_id']) for row in assignments} != set(pack['rules']):
        raise ValueError('Missing rule or assignment')
    traces={};predictions=[]
    with closing(open_chart(export/'chart.sqlite')) as db:
        for row in assignments:
            k=str(row['annotation_id']);subject=subjects[row['patient']]
            trace=screen(search(db,subject),subject,pack,row['study'],k)
            traces[k]=trace;v=trace['criteria'][k]
            predictions.append(dict(annotation_id=k,subject=subject,study=row['study'],result=v['state'],
                                    source_resources=' | '.join(v['evidence']),source_sentences=v['source_sentences']))
    frozen=fingerprint(predictions)
    # Historical states and publisher labels only enter after prediction.
    with (R9/'export/matching.csv').open() as f:
        prior={r['annotation_id']:r for r in csv.DictReader(f)}
    for r in predictions:
        baseline=prior[r['annotation_id']]
        r.update(previous=baseline['fhir_result'],expert=baseline['expert_state'])
    def counts(values):return dict(Counter(values))
    decided=[r for r in predictions if r['result'] in ('MET','NOT_MET')]
    if any(not r['source_resources'] or not r['source_sentences'] for r in decided):
        raise ValueError('Decisive result lacks a source')
    requests={q['id']:q['route'] for v in traces.values() for q in v['requests']}
    # Deduplicate unresolved engineering work by exact contract across study versions.
    gaps={}
    for k,trace in traces.items():
        if trace['criteria'][k]['state'] in {'MET','NOT_MET','NOT_APPLICABLE'}:continue
        for q in trace['requests']:
            if q['route']!='engineering':continue
            gaps.setdefault(q['contract'],set()).add(k)
    summary=dict(distinct_engineering_contracts=len(gaps),cases=len(predictions),outcomes=counts(r['result'] for r in predictions),
                 changed=counts(r['previous']+' -> '+r['result'] for r in predictions if r['previous']!=r['result']),
                 definite=len(decided),agreed_definite=sum(r['result']==r['expert'] for r in decided),
                 exact_state=sum(r['result']==r['expert'] for r in predictions),
                 distinct_requests=counts(requests.values()),prediction_sha256=frozen,catalog_sha256=pack['sha256'])
    out.mkdir(parents=True,exist_ok=True)
    with (out/'matching.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=predictions[0]);w.writeheader();w.writerows(predictions)
    with (out/'engineering_mappings.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['contract','fact','scope','criterion_pairs','annotation_ids'])
        for cid,ids in sorted(gaps.items(),key=lambda item:(-len(item[1]),item[0])):
            spec=pack['contracts'][cid]['spec']
            w.writerow([cid,spec['label'],spec['scope'],len(ids),' | '.join(sorted(ids,key=int))])
    write_json(out/'traces.json',traces);write_json(out/'summary.json',summary)
    return summary

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export',type=Path,nargs='?',default=R9/'export')
    parser.add_argument('--catalog',type=Path,default=HERE/'compiled.json')
    parser.add_argument('--out',type=Path,default=HERE/'results')
    parser.add_argument('--subject');parser.add_argument('--study');parser.add_argument('--criterion')
    args=parser.parse_args()
    pack=verify(read_json(args.catalog))
    if args.subject or args.study or args.criterion:
        if not args.subject or not args.study:parser.error('Supply both --subject and --study.')
        with closing(open_chart(args.export/'chart.sqlite')) as db:
            result=screen(search(db,args.subject),args.subject,pack,args.study,args.criterion)
    else:result=replay(args.export,args.out,pack)
    print(json.dumps(result,indent=2))
