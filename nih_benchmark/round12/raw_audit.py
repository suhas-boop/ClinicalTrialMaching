"""Score direct prose intake against existing source-reviewed values and actual rules."""
import csv
from collections import Counter
from intake import HERE,R9,plain_chart,load,LOCAL
from screen import R11,verify,screen
from match import write_json
from record_facts import UNITS
from convert import rid,review_table
def audit():
    notes=load(R9/'notes.json');reviewed=review_table();pack=verify(load(R11/'compiled.json'));obtained={};resources={}
    expected=set();seen=set();actual_rows=[]
    for pid,note in notes.items():
        for i,t,k,quote,context,qty in reviewed.get(pid,[]):
            if t=='Observation' and k in UNITS and qty and context=='presentation':
                expected.add((pid,i,k,float(qty[0]),qty[1]))
            if t=='MedicationStatement' and context=='active':expected.add((pid,i,k,'active',''))
        if pid=='sigir-201426':continue  # The exported Group has no individual patient chart.
        b,links=plain_chart(pid,note,'2026-01-01T00:00:00Z');items=[e['resource'] for e in b['entry']]
        resources[pid]=items
        index={rid(r):r for r in items}
        for l in links:
            r=index[l['resource']];cc=r.get('code',r.get('medicationCodeableConcept',{}));code=next(c['code'] for c in cc['coding'] if c['system']==LOCAL)
            if code in UNITS and code!='age-at-presentation':
                v=r['valueQuantity'];seen.add((pid,l['sentences'][0],code,v['value'],v['code']))
            if r['resourceType']=='MedicationStatement':
                seen.add((pid,l['sentences'][0],cc['text'],'active',''))
    base=load(R11/'results/traces.json')
    with (R11/'results/matching.csv').open() as f:labels={r['annotation_id']:r for r in csv.DictReader(f)}
    for a in load(R9/'assignments.json'):
        k=str(a['annotation_id']);pid=a['patient'];label=labels[k]
        # Group cases retain only their scope routing.
        if pid not in resources:
            bundle=load(R9/'export/bundles'/(pid+'.json'));items=[e['resource'] for e in bundle['entry']]
        else:items=resources[pid]
        got=screen(items,label['subject'],pack,a['study'],k)['criteria'][k]['state']
        actual_rows.append(dict(annotation=k,subject=pid,raw=got,reference=label['expert'],enriched=label['result']))
    groups={}
    for tag,select in [('numeric',lambda r:r[4]!=''),('medication',lambda r:r[4]=='')]:
        target={r for r in expected if select(r)}; found={r for r in seen if select(r)}
        groups[tag]=dict(recovered=len(target&found),reference_count=len(target),reference_only=sorted(target-found),other_predictions=sorted(found-target))
    result=dict(reference_recovery=groups,raw_screen=dict(pairs=len(actual_rows),definite=sum(r['raw'] in ('MET','NOT_MET') for r in actual_rows),
        agreeing_definite=sum(r['raw']==r['reference'] and r['raw'] in ('MET','NOT_MET') for r in actual_rows),
        state_counts=dict(Counter(r['raw'] for r in actual_rows))))
    write_json(HERE/'results/raw_evaluation.json',result)
    with (HERE/'results/raw_pairs.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=actual_rows[0]);w.writeheader();w.writerows(actual_rows)
    return result
if __name__=='__main__':print(audit())
