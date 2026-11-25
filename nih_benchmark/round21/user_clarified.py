"""Replay a user's clarification of the published symptom list against the adjudicated benchmark."""
import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'round20'))
from respiratory import BENCH, DECISIVE, frozen_assignments, predict, read_json, R11, save, verify
from review706 import clarify, release
from catalog import verify as verify_catalog
from match import screen
from run import fingerprint

QUESTION = ("For protocol AD0152015, does any one of the five listed symptoms satisfy the inclusion "
            "criterion without a separate diagnosis of pelvic congestion? If so, please identify the "
            "protocol version and clause.")


def validated_interpretation(answer, pack, study, criterion):
    if (study, criterion) != (clarify.STUDY, clarify.CASE):
        raise ValueError('The clarification applies only to its registered criterion')
    verify_catalog(pack)
    if fingerprint(pack['rules'][criterion]) != release.BASE_ENTRY_SHA256:
        raise ValueError('Original criterion source or rule changed')
    original = clarify.packet()
    expected = dict(study=study, criterion=criterion, protocol_id='AD0152015',
                    question=QUESTION, source_role='user', governing_protocol_version=None,
                    governing_protocol_clause=None, source_authority_verified=False)
    if (not isinstance(answer, dict) or set(answer) != set(expected) | {'answer'}
            or any(answer[k] != v for k, v in expected.items())
            or answer['source_authority_verified'] is not False):
        raise ValueError('Clarification has a different source, scope or question')
    if not isinstance(answer['answer'], str) or answer['answer'].strip().casefold() != 'yes':
        raise ValueError('Only an affirmative response answers this question')
    # These are the two interpretation choices contained in the user's question.
    spec = {'operator': 'ANY', 'requirement': 'symptoms_suffice'}
    rule = clarify.reviewed_rule(spec)
    user_provenance = dict(source_role='user', answer=answer['answer'], question=QUESTION,
                           study=study, criterion=criterion, protocol_id=answer['protocol_id'],
                           registry_sha256=original['registry_sha256'], answer_sha256=fingerprint(answer),
                           interpretation=spec, rule_sha256=fingerprint(rule),
                           governing_protocol_version=None, governing_protocol_clause=None,
                           source_authority_verified=False)
    return rule, user_provenance


def screen_user_clarified(resources, subject, pack, study, criterion, answer=None):
    if answer is None:
        return screen(resources, subject, pack, study, criterion)
    rule, source = validated_interpretation(answer, pack, study, criterion)
    return release._screen_interpretation(resources, subject, pack, study, criterion, rule,
                                          'user_clarification', source)


def replay(answer):
    prior = predict()
    pack = verify(read_json(R11 / 'compiled.json'))
    # Check the request even if someone removes its assignment from the input.
    validated_interpretation(answer, pack, answer['study'], answer['criterion'])
    by_case = {r['case']: r for r in prior['rows']}
    rows = []
    for assignment, subject, resources, hashes in frozen_assignments():
        study, case = assignment['study'], str(assignment['annotation_id'])
        baseline = by_case[case]
        if (baseline['subject'], baseline['study'], baseline['source_sha256']) != (subject, study, hashes[subject]):
            raise ValueError('Mismatch between assigned case, subject or patient note')
        row = dict(case=case, study=study, subject=subject, source_sha256=hashes[subject],
                   strict=baseline['strict'], supported_exam=baseline['supported_exam'],
                   strict_plus_user=baseline['strict'], exam_plus_user=baseline['supported_exam'])
        if (study, case) == (answer['study'], answer['criterion']):
            trace = screen_user_clarified(resources, subject, pack, study, case, answer)
            actual = trace['criteria'][case]['state']
            if trace['source_sha256'] != row['source_sha256']:
                raise ValueError('Clarified evaluation used a different patient source')
            row.update(strict_plus_user=actual, exam_plus_user=actual, clarification_trace=trace)
        rows.append(row)
    if len(rows) != 134 or len(by_case) != len(rows) or sum('clarification_trace' in r for r in rows) != 1:
        raise ValueError('Unexpected assignment or clarification coverage')
    return dict(catalog_sha256=pack['sha256'], user_response=answer, user_response_sha256=fingerprint(answer),
                prior_predictions_sha256=sha256((json.dumps(prior, indent=2) + '\n').encode()).hexdigest(), rows=rows)


def run(out, answer):
    out.mkdir(parents=True, exist_ok=True)
    freeze = out / 'predictions_before_reference.json'
    save(freeze, replay(answer))
    frozen = freeze.read_bytes()
    rows = json.loads(frozen)['rows']
    with (BENCH / 'round13/134_predictions.csv').open() as reference_file:
        gold = {r['annotation']: r['reference'] for r in csv.DictReader(reference_file)}
    if {r['case'] for r in rows} != set(gold):
        raise ValueError('Assignment set changed')
    result = dict(assignments=len(rows), physician_definitive=sum(v in DECISIVE for v in gold.values()),
                  prediction_sha256=sha256(frozen).hexdigest(), user_responses=1,
                  independently_verified_protocol_responses=0)
    for arm in ('strict', 'supported_exam', 'strict_plus_user', 'exam_plus_user'):
        decisions = [r for r in rows if r[arm] in DECISIVE]
        result[arm] = dict(agreements=sum(r[arm] == gold[r['case']] for r in decisions),
                           disagreements=sum(gold[r['case']] in DECISIVE and r[arm] != gold[r['case']] for r in decisions),
                           definitive_on_indeterminate=sum(gold[r['case']] not in DECISIVE for r in decisions))
    result['changed_from_supported_exam'] = [
        dict(case=r['case'], previous=r['supported_exam'], current=r['exam_plus_user'], physician_reference=gold[r['case']])
        for r in rows if r['exam_plus_user'] != r['supported_exam']]
    save(out / 'score.json', result)
    return result


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--out', type=Path, required=True)
    cli.add_argument('--user-answer', type=Path, default=HERE / 'user_answer.json')
    args = cli.parse_args()
    print(json.dumps(run(args.out, read_json(args.user_answer)), indent=2))
