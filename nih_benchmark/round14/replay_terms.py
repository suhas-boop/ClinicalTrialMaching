"""Apply the opt-in policy to every frozen assignment before opening the evaluation labels."""
import csv
import json
from term_policy import HERE, read_json, verify, prescreen, plain_chart

def run():
    root=HERE.parent
    pack=verify(read_json(root/'round11/compiled.json'))
    source=root/'round9'
    notes=read_json(source/'notes.json')
    subjects={r['case']:r['subject'] for r in read_json(source/'export/cases.json')}
    bundles={}
    predictions={}
    for a in read_json(source/'assignments.json'):
        patient=a['patient']
        if patient not in bundles:
            if subjects[patient].startswith('Group/'):
                b=read_json(source/'export/bundles'/(patient+'.json'))
            else:
                b,_=plain_chart(patient,notes[patient],'2026-01-01T00:00:00Z')
            bundles[patient]=[e['resource'] for e in b['entry']]
        key=str(a['annotation_id'])
        output=prescreen(bundles[patient],subjects[patient],pack,a['study'],key)
        predictions[key]=(output['criteria'][key]['state'],output['research_prescreen'])
    with (root/'round13/134_predictions.csv').open() as f:
        labels={r['annotation']:r for r in csv.DictReader(f)}
    assert set(predictions)==set(labels)
    direct=('MET','NOT_MET')
    extras={k:v[1] for k,v in predictions.items() if v[1]['state']=='SUPPORTED_PENDING_MEASUREMENT'}
    return dict(assignments=len(predictions),reference_definite=sum(r['reference'] in direct for r in labels.values()),
                direct_states_changed=[k for k,v in predictions.items() if v[0]!=labels[k]['current']],
                direct_agreeing=sum(v[0] in direct and v[0]==labels[k]['reference'] for k,v in predictions.items()),
                additional_prescreen_supported=extras,additional_prescreen_labeled_met=sum(labels[k]['reference']=='MET' for k in extras))
if __name__=='__main__':
    data=json.dumps(run(),indent=2)
    print(data)
    (HERE/'term_policy_receipt.json').write_text(data+'\n')
