"""Unblind after verifying the prediction freeze, then score patient-side eligibility."""
import ast, csv, hashlib, json, sys
from collections import Counter
from pathlib import Path
import duckdb
root=Path(__file__).resolve().parent
for line in (root/'FREEZE.sha256').read_text().splitlines():
 digest,name=line.split('  ');assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest
rows=json.loads((root/'predictions.json').read_text())
labels={i:(label,s) for i,label,s in duckdb.connect().execute("select annotation_id,expert_eligibility,expert_sentences from read_parquet(?)",[sys.argv[1]]).fetchall()}
mapping={'included':'MET','not included':'NOT_MET','excluded':'NOT_MET','not excluded':'MET','not applicable':'NOT_APPLICABLE','not enough information':'MISSING_DATA'}
for r in rows:
 label,s=labels[r['annotation_id']]
 cited=ast.literal_eval(s) if s else []
 r.update(expert_label=label,expert_state=mapping[label],expert_sentences=cited,agrees=r['state']==mapping[label],evidence_exact=set(r['sentences'])==set(cited))
with (root/'results.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
print(Counter((r['state'],r['expert_state']) for r in rows))
print('binary',[(r['annotation_id'],r['state'],r['expert_label'],r['sentences'],r['expert_sentences']) for r in rows if r['state'] in ('MET','NOT_MET')])
print('agreed',sum(r['agrees'] for r in rows),'ref',Counter(r['expert_state'] for r in rows))
for r in rows:
 print(r['annotation_id'],r['state'],r['expert_state'],r['expert_sentences'])
