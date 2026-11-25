"""Join frozen predictions to physician labels and export the two-round comparison."""
import csv,json
from collections import Counter
from pathlib import Path
from hashlib import sha256
root=Path(__file__).resolve().parent
for line in (root/'round2/REVISED.sha256').read_text().splitlines():
 digest,name=line.split('  ');assert sha256((root/'round2'/name).read_bytes()).hexdigest()==digest
joined=[];summary=[]
for name,path in [('pilot',root),('holdout',root/'round2')]:
 prior={int(r['annotation_id']):r for r in csv.DictReader((path/'results.csv').open())}
 revised=json.loads((path/'revised.json').read_text())
 for r in revised:
  old=prior[r['annotation_id']]
  joined.append({'round':name,'annotation_id':r['annotation_id'],'patient':r['patient_id'],'trial':r['trial_id'],
    'criterion':r['criterion_text'],'type':r['criterion_type'],'original':old['state'],'revised':r['state'],
    'expert':old['expert_state'],'expert_source_label':old['expert_label'],'decision_sentences':r['sentences'],
    'partial_sentences':r['partial_sentences'],'expert_sentences':old['expert_sentences'],
    'reason':r['reason'],'request_ids':r['request_ids']})
 panel=[r for r in joined if r['round']==name]; binary=[x for x in panel if x['revised'] in ('MET','NOT_MET')]
 requests=json.loads((path/'requests.json').read_text())
 summary.append(dict(round=name,patients=len({r['patient'] for r in panel}),trials=len({r['trial'] for r in panel}),
  rows=len(panel),binary=len(binary),binary_agree=sum(x['revised']==x['expert'] for x in binary),
  gold_binary=sum(x['expert'] in ('MET','NOT_MET') for x in panel),
  exact_sentences=sum(str(x['decision_sentences'])==x['expert_sentences'] for x in binary),
  original_exact_states=sum(x['original']==x['expert'] for x in panel),
  revised_exact_states=sum(x['revised']==x['expert'] for x in panel),
  review_routes=Counter(x['route'] for x in requests),evidence_retained_unresolved=sum(bool(x['partial_sentences']) and x not in binary for x in panel)))
with (root/'all_results.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=joined[0]);w.writeheader();w.writerows(joined)
(root/'summary.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary))
