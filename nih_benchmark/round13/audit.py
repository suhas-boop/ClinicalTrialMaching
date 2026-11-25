"""Replay normal screening before loading reference labels, then audit the frozen misses."""
import ast
import csv
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / 'round12'))
from intake import plain_chart
from screen import screen, verify

def read(path):
    return json.loads(path.read_text())

def rows(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))

def write_csv(name, data, output):
    with (output / name).open('w',newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(data[0]))
        writer.writeheader()
        writer.writerows(data)

def run(output=HERE):
    output.mkdir(parents=True, exist_ok=True)
    pack = verify(read(ROOT / 'round11/compiled.json'))
    notes = read(ROOT / 'round9/notes.json')
    subjects = {r['case']:r['subject'] for r in read(ROOT / 'round9/export/cases.json')}
    charts = {}
    traces = {}
    for a in read(ROOT / 'round9/assignments.json'):
        patient = a['patient']
        if patient not in charts:
            if subjects[patient].startswith('Group/'):
                bundle = read(ROOT / 'round9/export/bundles' / (patient+'.json'))
            else:
                bundle,_ = plain_chart(patient, notes[patient], '2026-01-01T00:00:00Z')
            charts[patient] = [entry['resource'] for entry in bundle['entry']]
        key = str(a['annotation_id'])
        traces[key] = screen(charts[patient], subjects[patient], pack, a['study'], key)
    # Prediction is complete. Reviewer citations and comparison states enter here.
    expert = {r['annotation_id']: r for r in rows(ROOT / 'round8/results/scored_cases.csv')}
    baseline = rows(ROOT / 'round12/results/raw_pairs.csv')
    review = {}
    for path in [ROOT / 'round11/chart_review.psv', HERE / 'review.psv']:
        for line in path.read_text().splitlines():
            key, stmt = line.split('|', 1)
            review[key] = stmt
    audit, predictions, work = [], [], {}
    definite = {'MET','NOT_MET'}
    for old in baseline:
        key,pid,ref = old['annotation'],old['subject'],old['reference']
        trace = traces[key]
        c = trace['criteria'][key]
        state = c['state']
        predictions.append(dict(annotation=key,previous=old['raw'],current=state,reference=ref))
        if ref not in definite or old['raw'] in definite:
            continue
        cited = ast.literal_eval(expert[key]['expert_sentences'])
        original = notes[pid].splitlines()
        req = trace['requests']
        for q in req:
            w=work.setdefault(q['id'],dict(id=q['id'],route=q['route'],request=q['request'],cases=[]))
            w['cases'].append(key)
        fact_values = c['facts']
        related = {k:v['related_findings'] for k,v in fact_values.items() if v.get('related_findings')}
        note = review[key] if old['raw']=='MISSING_DATA' else c['reason']
        selectors = {}
        for name, fact in fact_values.items():
            if fact['state'] != 'AVAILABLE' and fact['contract'] in pack['contracts']:
                definition = pack['contracts'][fact['contract']]
                selectors[name] = dict(role=definition['spec']['role'], paths=definition['native'])
        audit.append(dict(case=key,study=expert[key]['study'],patient=pid,criterion=expert[key]['criterion'],
            reference=ref,baseline=old['raw'],replay=state,
            physician_source_lines=json.dumps(cited),physician_cited_text=' | '.join(original[i] for i in cited),
            chart_review=note,source_document='DocumentReference/'+pid+'-note',
            rule_expression=json.dumps(pack['rules'][key]['rule']['expression']),
            facts_and_evidence=json.dumps(fact_values,sort_keys=True),
            required_evidence_selectors=json.dumps(selectors,sort_keys=True),
            related_qualitative_evidence=json.dumps(related,sort_keys=True),
            requests=' | '.join(q['request'] for q in req),routes=' | '.join(sorted({q['route'] for q in req}))))
    assert len(predictions)==len(traces)==134 and len(audit)==85
    write_csv('85_case_audit.csv',audit,output)
    write_csv('134_predictions.csv',predictions,output)
    write_csv('action_queue.csv',[dict(**{k:v for k,v in w.items() if k!='cases'},cases=','.join(w['cases'])) for w in work.values()],output)
    summary=dict(replayed=len(predictions),audited=len(audit),reference_definite=sum(r['reference'] in definite for r in predictions),
        definite=sum(r['current'] in definite for r in predictions),agreeing_definite=sum(r['current'] in definite and r['current']==r['reference'] for r in predictions),
        changed=[r for r in predictions if r['previous']!=r['current']],
        primary=dict(Counter(r['replay'] for r in audit)),request_counts=dict(Counter(w['route'] for w in work.values())),
        physician_without_sentence=sum(r['physician_source_lines']=='[]' for r in audit),
        missing_data_without_sentence=sum(r['baseline']=='MISSING_DATA' and r['physician_source_lines']=='[]' for r in audit),
        with_related_evidence=[r['case'] for r in audit if r['related_qualitative_evidence']!='{}'])
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (output/'raw_traces.json').write_text(json.dumps(traces,indent=1)+'\n')
    return summary

if __name__=='__main__':
    print(json.dumps(run(),indent=2))
