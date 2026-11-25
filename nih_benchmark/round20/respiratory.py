"""Compare direct evidence and two independently sourced clinical term interpretations."""
import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'round19'))
from exam_bounds import BENCH, DECISIVE, evaluate, frozen_assignments, read_json, R11, verified_sources, verify

# Also block common numeric respiratory-rate notations outside the numeric extractor's
# grammar. A number in a numbered source-line prefix is not a measured breathing rate.
COMPACT_RR = re.compile(
    r'(?<!\w)(?:R|RR|resp(?:iratory)?[. -]?rate|respir(?:ation)?s?)\s*'
    r'(?:[=:]\s*)?(?:[<>≤≥~]\s*)?\d+(?:\.\d+)?\b|'
    r'(?<!\w)\d+(?:\.\d+)?\s*(?:breaths?|respirations?)\s*(?:/|per)\s*min',
    re.IGNORECASE)


def infer(resources, subject, pack, study, case, policy, sources):
    """Evaluate a complete reviewed rule, retaining the leaf that satisfies its OR."""
    row = evaluate(resources, subject, pack, study, case, policy, sources,
                   compact_rate_pattern=COMPACT_RR)
    # The historic R19 evaluator reports the textbook arm. Determine which part
    # is established in a note with no patient-source convention for tachypnea.
    textbook_state = row.pop('exam_arm')
    row.update(supported_exam=row['strict'], textbook_sensitivity=textbook_state,
               lower_cutoff_sensitivity=row['strict'])
    if 'evidence' not in row:
        return row
    proof = row.pop('evidence')
    row['respiratory_review'] = proof
    tree = proof['comparison']
    # Both reviewed contracts concern a single positive lower-bound leaf,
    # optionally one arm of a complete disjunction; additional conjunctions
    # or nested branches need a separately reviewed proof structure.
    leaves = tree.get('any', [tree])
    matching = [leaf for leaf in leaves if leaf.get('fact') == policy['fact']
                and leaf.get('op') in {'ge','gt'}]
    if len(matching) != 1:
        raise ValueError('Expected a unique directly sufficient respiratory branch')
    leaf = matching[0]
    if proof['open_lower_bound'] < leaf['value']:
        raise ValueError('Declared lower bound cannot establish the criterion')
    proof['sufficient_leaf'] = leaf
    proof['alternative_definition'] = dict(policy['alternative'],
        proves_same_leaf=policy['alternative']['open_lower_bound'] >= leaf['value'])
    if proof['alternative_definition']['proves_same_leaf']:
        row['lower_cutoff_sensitivity'] = textbook_state
    proof['publication_examples'] = policy['clinical_usage']
    proof['source_convention'] = policy['source_convention']
    proof['decision'] = ('The chart establishes the qualitative finding. The source gives no quantitative '
                         'definition. An adult clinical use below the trial cutoff prevents an unqualified inference.')
    proof['other_alternatives'] = [item for item in leaves if item != leaf]
    return row


def save(path, obj):
    path.write_text(json.dumps(obj, indent=2) + '\n')


def predict():
    prior = read_json(BENCH / 'round19/term_contract.json')
    policy = read_json(HERE / 'term_contract.json')
    previous_sources = verified_sources(prior)
    sources = verified_sources(policy)
    catalog = verify(read_json(R11 / 'compiled.json'))
    rows = []
    for assignment, subject, resources, hashes in frozen_assignments():
        study = assignment['study']
        case = str(assignment['annotation_id'])
        original = evaluate(resources, subject, catalog, study, case, prior, previous_sources)
        extra = infer(resources, subject, catalog, study, case, policy, sources)
        if (original['source_sha256'] != hashes[subject] or extra['source_sha256'] != hashes[subject]
                or extra['strict'] != original['strict']):
            raise ValueError('Patient source or original disposition changed')
        row = dict(case=case, subject=subject, study=study, source_sha256=hashes[subject],
                   strict=original['strict'], heart_exam=original['exam_arm'],
                   supported_exam=original['exam_arm'], textbook_sensitivity=original['exam_arm'],
                   lower_cutoff_sensitivity=original['exam_arm'])
        if 'evidence' in original:
            row['evidence'] = original['evidence']
        if 'respiratory_review' in extra:
            if 'evidence' in original:
                raise ValueError('A criterion matched two evidence contracts')
            row['respiratory_review'] = extra['respiratory_review']
            for arm in ('supported_exam', 'textbook_sensitivity', 'lower_cutoff_sensitivity'):
                row[arm] = extra[arm]
        rows.append(row)
    return dict(catalog_sha256=catalog['sha256'], heart_policy=prior, respiratory_policy=policy, rows=rows)


def run(out):
    out.mkdir(parents=True, exist_ok=True)
    freeze = out / 'predictions_before_reference.json'
    save(freeze, predict())
    frozen = freeze.read_bytes()
    rows = json.loads(frozen)['rows']
    with (BENCH / 'round13/134_predictions.csv').open() as f:
        reference = {r['annotation']:r['reference'] for r in csv.DictReader(f)}
    if len(rows) != 134 or {r['case'] for r in rows} != set(reference):
        raise ValueError('Changed assignment population')
    result = dict(assignments=len(rows), physician_definitive=sum(v in DECISIVE for v in reference.values()),
                  freeze_sha256=sha256(frozen).hexdigest())
    for arm in ('strict','heart_exam','supported_exam','textbook_sensitivity','lower_cutoff_sensitivity'):
        scored = [r for r in rows if r[arm] in DECISIVE]
        result[arm] = dict(agreements=sum(r[arm] == reference[r['case']] for r in scored),
                           disagreements=sum(reference[r['case']] in DECISIVE and r[arm] != reference[r['case']] for r in scored),
                           definitive_on_indeterminate=sum(reference[r['case']] not in DECISIVE for r in scored))
    result['changed_from_r19'] = [
        dict(case=r['case'], prior=r['heart_exam'], current=r['supported_exam'], reference=reference[r['case']])
        for r in rows if r['supported_exam'] != r['heart_exam']]
    result['changed_only_in_textbook_sensitivity'] = [
        dict(case=r['case'], primary=r['supported_exam'], sensitivity=r['textbook_sensitivity'],
             reference=reference[r['case']]) for r in rows if r['textbook_sensitivity'] != r['supported_exam']]
    save(out / 'score.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    print(json.dumps(run(parser.parse_args().out), indent=2))
