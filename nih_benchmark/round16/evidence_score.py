"""Same-denominator evidence replay with independently attributable input and policy arms."""
import argparse
import csv
from datetime import date
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
sys.path.insert(0, str(HERE/'physician_source'))
from retrospective_review import review
from literal_scope import replay, frozen_assignments, read_json, verify, R11, screen
from review706 import clarify

DEFINITE = {'MET','NOT_MET'}


def write(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False)+'\n')


def score(rows, column):
    correct = wrong = unverified = 0
    for r in rows:
        p, reference = r[column], r['physician_reference']
        if p not in DEFINITE:
            continue
        if reference not in DEFINITE:
            unverified += 1
        elif p == reference:
            correct += 1
        else:
            wrong += 1
    return {'agreeing_definite':correct,'disagreeing_definite':wrong,
            'definite_on_reference_indeterminate':unverified}


def run(out, authority=None):
    out.mkdir(parents=True,exist_ok=True)
    # Source ID and assertion type are verified without opening physician eligibility labels.
    reviewed = review(BENCH, HERE/'physician_source/answers-2014.xlsx')
    assignments = json.loads((BENCH/'round9/assignments.json').read_text())
    subject_ids = reviewed['records'].keys()
    reviewed_pairs = sum(a['patient'] in subject_ids for a in assignments)
    original = replay()
    scoped = {k:v['trace']['criteria'][k] for k,v in original.items()}
    strict = {k:v['strict_state'] for k,v in original.items()}
    pack = verify(read_json(R11 / 'compiled.json'))
    after = {}
    decisive_traces = {}
    notes = read_json(BENCH / 'round9/notes.json')
    reviewed_trace = None
    if not authority and (out/'actual_authority_result.json').exists():
        raise ValueError('Use a separate output directory for an unadjudicated replay.')
    for row, subject, resources, approved in frozen_assignments():
        key = str(row['annotation_id'])
        if authority and row['study'] == clarify.STUDY and key == clarify.CASE:
            from review706.release import screen_reviewed
            trace = screen_reviewed(resources, subject, pack, row['study'], key, **authority)
            reviewed_trace = trace
        else:
            trace = screen(resources, subject, pack, row['study'], key)
        result = trace['criteria'][key]
        if trace['source_sha256'] != approved[subject]:
            raise ValueError('Mismatched source in the replay')
        if result['state'] in DEFINITE and (not result['evidence'] or not result['source_sentences']):
            raise ValueError('Definitive result lacks source-linked patient evidence')
        if result['state'] in DEFINITE:
            lines = notes[row['patient']].splitlines()
            decisive_traces[key] = {
                'subject': subject, 'study': row['study'], 'criterion': key,
                'criterion_type': pack['rules'][key]['source']['criterion_type'],
                'criterion_text': pack['rules'][key]['source']['criterion_text'],
                'state': result['state'], 'source_sha256': trace['source_sha256'],
                'catalog_sha256': trace['catalog_sha256'], 'references': result['evidence'],
                'cited_lines': [{'line': i, 'text': lines[i]} for i in result['source_sentences']],
            }
        after[key] = result['state']
    if reviewed_trace is not None:
        write(out/'actual_authority_result.json',reviewed_trace)
    # Persist the predictions and their decisive citations before opening the reference file.
    blind = [
        dict(case=str(a['annotation_id']), study=a['study'], patient=a['patient'],
             original_strict=strict[str(a['annotation_id'])], with_authority=after[str(a['annotation_id'])],
             literal_cohort=scoped[str(a['annotation_id'])]['state'])
        for a in assignments
    ]
    write(out/'predictions_before_reference.json',{'rows':blind,'definitive_evidence':decisive_traces})
    # Read labels only after every assigned pair has been screened.
    with (BENCH/'round13/134_predictions.csv').open() as stream:
        references = {r['annotation']:r['reference'] for r in csv.DictReader(stream)}
    if set(original) != set(references):
        raise ValueError('Population drift')
    rows=[]
    for a in assignments:
        k=str(a['annotation_id'])
        rows.append(dict(case=k,study=a['study'],patient=a['patient'],original_strict=strict[k],
                with_authority=after[k],literal_cohort=scoped[k]['state'],
                literal_used=original[k]['used'],physician_reference=references[k]))
    with (out/'all_pairs.csv').open('w',newline='') as stream:
        w=csv.DictWriter(stream,fieldnames=rows[0]); w.writeheader(); w.writerows(rows)
    write(out/'retrospective_source_review.json',reviewed)
    write(out/'literal_cohort_changes.json',{k:v for k,v in original.items() if v['used']})
    result=dict(assignments=len(rows),reference_definite=sum(v in DEFINITE for v in references.values()),
                original_strict=score(rows,'original_strict'),with_actual_authority=score(rows,'with_authority'),
                actual_authority_responses=int(authority is not None),literal_cohort=score(rows,'literal_cohort'),
                changed_by_authority=[k for k in strict if strict[k]!=after[k]],
                changed_only_by_literal_cohort=[k for k in strict if strict[k]!=scoped[k]['state']],
                new_source_patient_or_group_joins=len(subject_ids),assigned_pairs_in_new_source=reviewed_pairs,
                definitive_assertions_from_differential_column=sum(len(v['promoted_clinical_assertions']) for v in reviewed['records'].values()))
    write(out/'definitive_evidence.json',decisive_traces)
    write(out/'score.json',result)
    return result

if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--out',type=Path,default=HERE/'results')
    cli.add_argument('--answer',type=Path)
    cli.add_argument('--trust',type=Path)
    cli.add_argument('--governing-protocol',type=Path)
    cli.add_argument('--as-of',type=date.fromisoformat)
    args=cli.parse_args()
    review_inputs=[args.answer,args.trust,args.governing_protocol,args.as_of]
    if any(review_inputs) and not all(review_inputs):
        cli.error('Supply all four authority inputs together.')
    source=None
    if args.answer:
        source=dict(envelope=json.loads(args.answer.read_text()),trust=json.loads(args.trust.read_text()),
                    protocol_bytes=args.governing_protocol.read_bytes(),as_of=args.as_of)
        if source['envelope'] is None:
            cli.error('An empty answer cannot count as an authority response.')
    print(json.dumps(run(args.out,source),indent=2))
