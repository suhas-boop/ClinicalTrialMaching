"""Export reviewer questions and scope/coverage comparisons from verified run receipts."""
import csv,json
from collections import Counter
from run import HERE,DATA,table,dump

def report(out):
    scored=list(csv.DictReader((out/'scored_cases.csv').open()))
    pack=json.loads((out/'rules.json').read_text())
    prior={}
    for panel in (DATA,DATA/'round2',DATA/'round3'):
        records=json.loads((panel/('predictions.json' if panel.name=='round3' else 'revised.json')).read_text())
        for r in records:
            prior[str(r['annotation_id'])]=r.get('automatic',r)['state']
    questions=[];binary={'MET','NOT_MET'}
    for r in scored:
        k=r['annotation_id'];source=pack[k]['source'];rule=pack[k]['rule']
        if r['rule_status']=='CLINICIAN_INPUT':
            reg=source['registry']
            questions.append(dict(trial=r['study'],criterion_id=k,criterion=source['criterion_text'],
                                  question=rule['expression']['hold'],registry_url=reg['registry_url'],
                                  registry_sha256=reg['registry_sha256'],answer='',governing_protocol_section=''))
    table(out/'clinician_questions.csv',questions)
    runnable=[r for r in scored if r['rule_status']!='CLINICIAN_INPUT']
    lookup=list(csv.DictReader((out/'evidence_catalog.csv').open()))
    summary=dict(prior_binary=sum(s in binary for s in prior.values()),current_binary=sum(r['patient_result'] in binary for r in scored),
        prior_to_open=[dict(criterion=r['annotation_id'],old=prior[r['annotation_id']],new=r['patient_result'])
                       for r in scored if prior[r['annotation_id']] in binary and r['patient_result'] not in binary],
        distinct_contracts=len(lookup),supported_by_note_adapter=sum(k['note_reader']=='True' for k in lookup),
        executable_rules_all_leaves_have_note_adapter=sum(int(r['total_required_fact_types'])==int(r['note_reader_fact_count']) for r in runnable),
        executable_rules_some_leaves_have_note_adapter=sum(0<int(r['note_reader_fact_count'])<int(r['total_required_fact_types']) for r in runnable),
        executable_rules_normalized_input_only=sum(int(r['note_reader_fact_count'])==0 for r in runnable))
    dump(out/'coverage.json',summary)
if __name__=='__main__':report(HERE/'results')
