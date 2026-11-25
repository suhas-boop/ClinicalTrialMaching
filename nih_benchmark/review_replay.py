"""Apply the review layer to blinded public cases. Synthetic encounter metadata marks benchmark scope only."""
import argparse, base64, hashlib, json, re, sys
from collections import Counter
from pathlib import Path
base=Path(__file__).resolve().parent
sys.path.insert(0,str(base.parent/'criterion_workbench'))
from evidence_review import screen
from bindings import make_packet, contract, ref

# Reusable ownership decisions. Applicability, timing and source obligations remain in each rule.
roles={
 'study_personnel_confirm_mci_symptoms':'investigator',
 'enrolling_physician_considers_mycobacterial_culture_likely_positive':'investigator',
 'investigator_identified_unacceptable_risk_from_concomitant_condition':'investigator',
 'willing_to_provide_blood_samples':'patient','willing_to_store_samples':'patient',
 'enrolled_two_year_blinded_ASA_trial':'site','entered_three_year_ASA_extension':'site',
 'china_subject':'site','rapid_recovery_expected_after_surgical_removal':'investigator',
 'active_treatment_of_any_form_not_considered':'record',
}
def run(folder):
 rows=json.loads((folder/'blind.json').read_text());rules=json.loads((folder/'rules.json').read_text())
 notes=json.loads((folder/'facts.json').read_text());allrequests={};out=[]
 for r in rows:
  cid=str(r['annotation_id']);pid=r['patient_id'];rule=rules[cid]
  for k,spec in rule['facts'].items():
   spec['role']=roles.get(k,spec['role'])
  facts={k:v for k,v in notes.get(pid,{}).items() if k in rule['facts']}
  # This text dataset supplies no authenticated investigator or patient-role signatures.
  if any(rule['facts'][k]['role']!='record' for k in facts):
   raise ValueError('Authenticated signer required for non-record evidence')
  corpus={int(n):t for n,t in re.findall(r'^(\d+)\. (.*)$',r['note'],re.M)}
  version=hashlib.sha256(json.dumps(sorted((x['criterion_type'],x['criterion_text']) for x in rows
                                          if x['trial_id']==r['trial_id'])).encode()).hexdigest()
  p=make_packet({cid:rule},{cid:{k:v[0] for k,v in facts.items()}},r['trial_id'],version,patient=pid)
  refs={}
  for obj in (e['resource'] for e in p['bundle']['entry']):
   if obj['resourceType']=='DocumentReference':
    k=next(k for k in facts if obj['id']=='src-'+contract(rule['facts'][k]))
    ids=facts[k][1];assert ids and all(i in corpus for i in ids)
    refs[ref(obj)]=ids
    obj['content'][0]['attachment'].update(title=f'{pid}: {ids}',data=base64.b64encode(
        '\n'.join(corpus[i] for i in ids).encode()).decode())
  result=screen({cid:rule},p,r['trial_id'],version);v=result['criteria'][cid]
  ids=lambda refs_:sorted({i for rid in refs_ for i in refs.get(rid,[])})
  for q in result['requests']:
   item=allrequests.setdefault(q['id'],dict(q,criteria=[]))
   if cid not in item['criteria']:item['criteria'].append(cid)
  out.append(dict(annotation_id=int(cid),patient_id=pid,trial_id=r['trial_id'],criterion_type=r['criterion_type'],
                  criterion_text=r['criterion_text'],state=v['state'],sentences=ids(v['evidence']),reason=v['reason'],
                  partial_sentences=ids(v['partial_evidence']),request_ids=[q['id'] for q in result['requests']]))
 (folder/'revised.json').write_text(json.dumps(out,sort_keys=True,indent=2))
 (folder/'requests.json').write_text(json.dumps(list(allrequests.values()),sort_keys=True,indent=2))
 print(folder.name,Counter(x['state'] for x in out),Counter(x['route'] for x in allrequests.values()))
 print('unresolved with supporting sentences',sum(1 for x in out if x['state'] not in ('MET','NOT_MET','NOT_APPLICABLE') and x['partial_sentences']))
if __name__=='__main__':
 for folder in (base,base/'round2'):run(folder)
