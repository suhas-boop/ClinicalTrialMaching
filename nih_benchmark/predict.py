"""Evaluate frozen rules and sentence-backed abstractions with the original PocketMD evaluator."""
from pathlib import Path
import sys, json, hashlib, re, base64
root=Path(__file__).resolve().parent
release=Path(sys.argv[1]) if len(sys.argv)>1 else root.parent/'eight_rules/release'
sys.path.insert(0,str(release))
from bindings import make_packet,Snapshot,contract,ref
from rules_engine import evaluate,validate
read=lambda name:json.loads((root/name).read_text())
rows=read('blind.json');rules=read('rules.json');abstractions=read('facts.json');out=[]
for row in rows:
 cid=str(row['annotation_id']);pid=row['patient_id'];rule=rules[cid];validate(rule)
 values={k:v for k,v in abstractions.get(pid,{}).items() if k in rule['facts']}
 wording_hash=hashlib.sha256(row['criterion_text'].encode()).hexdigest()
 packet=make_packet({cid:rule},{cid:{k:v[0] for k,v in values.items()}},row['trial_id'],wording_hash,patient=pid)
 lines={int(i):s for i,s in re.findall(r'^(\d+)\. (.*)$',row['note'],re.M)}
 refs={}
 for entry in packet['bundle']['entry']:
  r=entry['resource']
  if r['resourceType']!='DocumentReference':continue
  k=next(k for k in values if r['id']=='src-'+contract(rule['facts'][k]))
  ids=values[k][1];assert ids and all(i in lines for i in ids)
  refs[ref(r)]=ids
  attach=r['content'][0]['attachment']
  attach.update(title=f'NIH benchmark {pid}, sentences {ids}',data=base64.b64encode('\n'.join(lines[i] for i in ids).encode()).decode())
 snap=Snapshot(packet['bundle'],packet['context'],row['trial_id'],wording_hash)
 v=evaluate(rule,snap)
 ids=sorted({i for ref_id in v['evidence'] for i in refs.get(ref_id,[])})
 assert v['state'] not in ('MET','NOT_MET') or ids
 out.append(dict(annotation_id=int(cid),patient_id=pid,trial_id=row['trial_id'],criterion_type=row['criterion_type'],criterion_text=row['criterion_text'],state=v['state'],sentences=ids,reason=v['reason']))
(root/'predictions.json').write_text(json.dumps(out,indent=2))
