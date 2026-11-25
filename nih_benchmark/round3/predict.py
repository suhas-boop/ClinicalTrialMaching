from pathlib import Path
import json,sys
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root.parents[1]/'criterion_workbench'))
from screen_vignette import evaluate_vignette
rows=json.loads((root/'blind.json').read_text())
rules=json.loads((root/'rules.json').read_text())
assisted=json.loads((root/'assisted_facts.json').read_text())
out=[]
for row in rows:
    i=str(row['annotation_id'])
    query=dict(rule=rules[i],patient=row['patient_id'],study=row['trial_id'],criterion_text=row['criterion_text'],note=row['note'])
    if i=='44':(root/'example_input.json').write_text(json.dumps(query,indent=2))
    v=dict(annotation_id=int(i),patient=row['patient_id'],trial=row['trial_id'],criterion=row['criterion_text'])
    for name,params in [('assisted_baseline',{'assisted':assisted.get(row['patient_id'],{}),'use_reader':False}),
                        ('automatic',{}),('combined',{'assisted':assisted.get(row['patient_id'],{})})]:
        v[name]=evaluate_vignette(**query,**params)
    out.append(v)
(root/'predictions.json').write_text(json.dumps(out,sort_keys=True,indent=2))
print({key:sum(r[key]['state'] in ('MET','NOT_MET') for r in out) for key in ('assisted_baseline','automatic','combined')})
