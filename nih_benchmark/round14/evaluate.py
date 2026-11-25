"""Reproduce the PocketMD R14 source-grounded benchmark and separate diagnostic arms."""
import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
sys.path.insert(0, str(BENCH / 'round13'))
from audit import read, rows, run as primary_replay
from record_arrivals import experiment
from replay_terms import run as prescreen_replay
from source_worklist import build_worklist, replay_scopes
from catalog import compile_pack, verify
sys.path.insert(0, str(HERE / 'organizer_sources'))
from source_join import join
from replay import run as organizer_replay
from summary_replay import run as summary_replay

DECISIVE = {'MET', 'NOT_MET'}


def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')


def table(path, items, fields):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(items)


def compute(out):
    out.mkdir(parents=True, exist_ok=True)
    pack = verify(read(BENCH / 'round11/compiled.json'))
    if pack['sha256'] != verify(compile_pack())['sha256']:
        raise ValueError('Recompile the catalog before replaying.')
    notes = read(BENCH / 'round9/notes.json')
    pinned = read(BENCH / 'round9/note_hashes.json')
    if {k:hashlib.sha256(v.encode()).hexdigest() for k,v in notes.items()} != pinned:
        raise ValueError('Frozen source notes changed.')
    assignments = read(BENCH / 'round9/assignments.json')
    replay = primary_replay(out)
    traces = read(out / 'raw_traces.json')
    full = build_worklist(replay_scopes(traces, assignments, pack), pack)
    save(out / 'all_work.json', full)
    pre = prescreen_replay()
    save(out / 'prescreen.json', pre)
    save(out / 'organizer_join.json', join(BENCH))
    expanded = organizer_replay(BENCH)
    save(out / 'organizer_replay.json', expanded)
    summaries = summary_replay(BENCH)
    save(out / 'organizer_summaries.json', summaries)
    synthetic = experiment()
    save(out / 'synthetic_record_arrivals.json', synthetic)
    # Reporting only. Each arm's predictions were made before comparisons with gold.
    predicted = rows(out / '134_predictions.csv')
    missed = {r['annotation'] for r in predicted if r['reference'] in DECISIVE and r['current'] not in DECISIVE}
    decisive = [r for r in predicted if r['current'] in DECISIVE]
    correct = [r for r in decisive if r['current'] == r['reference']]
    for row in decisive:
        key = row['annotation']
        result = traces[key]['criteria'][key]
        if not result['evidence'] or not result['source_sentences']:
            raise ValueError(f'Decision lacks source evidence for {key}')
    work = build_worklist(replay_scopes({k:v for k,v in traces.items() if k in missed}, assignments, pack), pack)
    save(out / 'remaining_work.json', work)
    tasks = []
    for group in work['groups']:
        ids = group['affected_criteria']
        tasks.append(dict(patient=group['scope']['subject'], study=group['scope']['study'],
                          document_family=group['source_family'], criteria_in_scope=len(ids),
                          criterion_ids=', '.join(ids),
                          evidence_sought=' | '.join(row['request'] for row in group['requests'])))
    table(out / 'record_requests_by_impact.csv', tasks, list(tasks[0]) if tasks else
          ['patient','study','document_family','criteria_in_scope','criterion_ids','evidence_sought'])
    # This counterfactual measures how much the metric rewards assuming that chart silence
    # clears an exclusion. No imputed result is returned by a matcher or put in a chart.
    fill = [r for r in predicted if r['current']=='MISSING_DATA'
            and pack['rules'][r['annotation']]['source']['criterion_type']=='exclusion']
    counterfactual = dict(pairs_reclassified=len(fill), reference_counts=dict(Counter(r['reference'] for r in fill)),
                          agrees_with_reference=sum(r['reference']=='MET' for r in fill),
                          disagrees_with_reference=sum(r['reference']!='MET' for r in fill))
    direct_by_case = {r['annotation']:r for r in predicted}
    pending = pre['additional_prescreen_supported']
    pending_correct = [k for k in pending if direct_by_case[k]['reference']=='MET']
    pending_patients = {a['patient'] for a in assignments if str(a['annotation_id']) in pending}
    triggered = {r['case']: r for r in summaries['cases'] if r['summary_evidence']}
    by_case = {str(a['annotation_id']):a for a in assignments}
    old_rules = read(BENCH / 'round8/results/rules.json')
    case_rows = []
    for row in predicted:
        if row['reference'] not in DECISIVE:
            continue
        key = row['annotation']
        current = pack['rules'][key]
        a = by_case[key]
        trace = traces[key]
        result = trace['criteria'][key]
        requests = trace['requests']
        source_lines = notes[a['patient']].splitlines()
        case_rows.append(dict(case=key, patient=a['patient'], study=a['study'],
                criterion=current['source']['criterion_text'], criterion_type=current['source']['criterion_type'],
                prior_rule='PROTOCOL_QUESTION' if 'hold' in old_rules[key]['rule']['expression'] else 'EXECUTABLE',
                current_rule='PROTOCOL_QUESTION' if 'hold' in current['rule']['expression'] else 'EXECUTABLE',
                patient_result=row['current'], physician_reference=row['reference'],
                decisive_evidence=' | '.join(result['evidence']) if row['current'] in DECISIVE else '',
                source_excerpt=' | '.join(source_lines[i] for i in result['source_sentences']) if row['current'] in DECISIVE else '',
                requests=' | '.join(q['request'] for q in requests),
                request_routes=', '.join(sorted({q['route'] for q in requests})),
                prescreen='PENDING_MEASUREMENT' if key in pending else '',
                extra_summary_citation='yes' if key in triggered else ''))
    table(out / '91_case_scorecard.csv', case_rows, list(case_rows[0]))
    # A protocol question can apply to multiple assigned pairs. Preserve the
    # study/version and all linked criteria under its stable request identifier.
    questions = {}
    for item in work['other_requests']:
        if item['route'] != 'protocol_review':
            continue
        row = questions.setdefault(item['request_id'], dict(study=item['scope']['study'],
                    study_version=item['scope']['study_version'], question=item['request'], criteria=set()))
        row['criteria'].update(item['criteria'])
    human = [dict(**{k:v for k,v in q.items() if k!='criteria'},criteria=', '.join(sorted(q['criteria'])))
             for q in questions.values()]
    table(out / 'trial_questions.csv', human, ['study','study_version','question','criteria'])
    summary = dict(benchmark='TrialGPT frozen patient–criterion assignments, retrospective development replay',
                   prior_executable=sum(r['prior_rule']=='EXECUTABLE' for r in case_rows),
                   current_executable=sum(r['current_rule']=='EXECUTABLE' for r in case_rows),
                   assignments=len(predicted), reference_definite=replay['reference_definite'],
                   strict_decisions=len(decisive), agreeing_strict_decisions=len(correct),
                   disagreeing_strict_decisions=len(decisive)-len(correct),
                   unresolved_reference_definite=len(missed), remaining_by_route=replay['primary'],
                   state_changes=replay['changed'], source_requests=len(tasks),
                   underlying_scoped_record_requests=work['unique_scoped_record_requests'],
                   unique_other_actions_by_route=dict(Counter(dict((r['request_id'],r['route']) for r in work['other_requests']).values())),
                   prescreen_cases=list(pending), matching_prescreen_cases=pending_correct,
                   prescreen_patients=len(pending_patients), published_source_criteria_replayed=expanded['assigned_criteria_replayed_per_arm'],
                   published_source_state_changes=expanded['eligibility_state_changes'],
                   summary_pairs_replayed=summaries['rule_pairs'], summary_cases_with_new_citations=summaries['summary_cited_by_rule'],
                   summary_outcome_changes=summaries['changed_outcomes'],
                   synthetic_scenarios=len(synthetic['scenarios']), excluded_from_primary=['synthetic controls','qualitative prescreen','public supplementary arm'],
                   exclusion_silence_sensitivity_only=counterfactual, catalog_sha256=pack['sha256'])
    save(out / 'scorecard.json', summary)
    return summary

if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--out', type=Path, default=HERE/'results')
    print(json.dumps(compute(cli.parse_args().out), indent=2))
