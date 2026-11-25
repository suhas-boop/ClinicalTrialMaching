import ast,csv,hashlib,json,sys
from collections import Counter
from pathlib import Path
import duckdb
root=Path(__file__).resolve().parent
for ln in (root/'freeze.sha256').read_text().splitlines():
 h,n=ln.split('  ');assert hashlib.sha256((root/n).read_bytes()).hexdigest()==h
rows=json.loads((root/'predictions.json').read_text())
previous={r['patient_id'] for p in (root.parent,root.parent/'round2') for r in json.loads((p/'blind.json').read_text())}
assert previous.isdisjoint(r['patient'] for r in rows)
gold={i:(l,ast.literal_eval(s) if s else []) for i,l,s in duckdb.connect().execute("SELECT annotation_id, expert_eligibility, expert_sentences FROM read_parquet(?) WHERE NOT training",[sys.argv[1]]).fetchall()}
states={'included':'MET','not excluded':'MET','not included':'NOT_MET','excluded':'NOT_MET','not applicable':'NOT_APPLICABLE','not enough information':'MISSING_DATA'}
summary=dict(patients=len(set(r['patient'] for r in rows)),trials=len(set(r['trial'] for r in rows)),criteria=len(rows),physician_decided=sum(states[gold[r['annotation_id']][0]] in ('MET','NOT_MET') for r in rows))
out=[]
for key in ('assisted_baseline','automatic','combined'):
 decided=agree=exact=overlap=0; counts=Counter()
 for r in rows:
  v=r[key];l,ids=gold[r['annotation_id']];state=states[l];counts[v['state']]+=1
  if v['state'] in ('MET','NOT_MET'):
   decided+=1;agree+=v['state']==state;exact+=set(v['sentences'])==set(ids);overlap+=bool(set(v['sentences'])&set(ids))
  out.append(dict(annotation_id=r['annotation_id'],patient=r['patient'],trial=r['trial'],criterion=r['criterion'],mode=key,state=v['state'],source_sentences=v['sentences'],partial_sentences=v['partial_sentences'],reason=v['reason'],expert_label=l,expert_state=state,expert_sentences=ids))
 summary[key]=dict(states=counts,decided=decided,agree=agree,exact_sentences=exact,overlap=overlap)
summary['baseline_to_combined_changes']=sum(r['assisted_baseline']['state']!=r['combined']['state'] for r in rows)
print(json.dumps(summary,indent=2));(root/'summary.json').write_text(json.dumps(summary,indent=2))
with (root/'results.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=out[0]);w.writeheader();w.writerows(out)
