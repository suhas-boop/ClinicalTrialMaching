"""Post-audit development checks kept separate from the blinded third-panel score."""
import json,sys
from pathlib import Path
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root.parents[1]/'criterion_workbench'))
from registry_context import packet
from screen_vignette import evaluate_vignette
from narrative_evidence import extract
summary={}
for panel in [root.parent,root.parent/'round2']:
 rows=json.loads((panel/'blind.json').read_text())
 rules=json.loads((panel/'rules.json').read_text())
 requests=json.loads((panel/'requests.json').read_text())
 previous=json.loads((panel/'revised.json').read_text())
 for row in rows:
  i=row['annotation_id']
  if i in (55,218,919):
   study=row['trial_id'];raw=(root/'context'/(study+'.json')).read_bytes()
   context=packet(study,row['criterion_text'],raw)
   summary[str(i)]={k:v for k,v in context.items() if k!='sections'}
   if i==218:
    age=extract(row['note'])['facts']['age_years']
    assert age['value']==30 and context['minimum_age']=='40 Years' and 'over 40 years old' in context['sections']['eligibilityCriteria']
    summary[str(i)].update(age=age,study_age_observation='Outside both posted age formulations. Renal field remains unresolved.')
 for_patient=[r for r in rows if r['patient_id']=='sigir-201426']
 if for_patient:
  old=set();new=set();independent=set()
  for r in for_patient:
   cid=r['annotation_id'];v=evaluate_vignette(rules[str(cid)],r['patient_id'],r['trial_id'],r['criterion_text'],r['note'])
   assert v['state']=='SOURCE_SCOPE_HOLD'
   new.update(q['id'] for q in v['requests'])
   prev=next(p for p in previous if p['annotation_id']==cid)
   old.update(prev['request_ids'])
  record_requests=sum(q['id'] in old and q['route']=='retrieve_record' for q in requests)
  independent=[q['request'] for q in requests if q['id'] in old and q['route']=='protocol_review']
  summary['group_case']=dict(criteria=len(for_patient),previous_record_requests=record_requests,subject_requests=len(new),independent_protocol_questions=independent)
(root/'development_checks.json').write_text(json.dumps(summary,indent=2));print(summary['group_case'])
