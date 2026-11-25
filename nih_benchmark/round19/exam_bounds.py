"""Replay the independent adult-exam interpretation of a registered quantitative predicate."""
import argparse
import base64
import csv
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
sys.path.insert(0, str(BENCH / 'round16'))
sys.path.insert(0, str(BENCH / 'round14'))
from literal_scope import frozen_assignments
from term_policy import NativeChart, prescreen, read_json, R11, verify

DECISIVE = {'MET', 'NOT_MET'}
# The numeric reader handles named, unit-bearing heart rates. Withhold a term
# inference even for compact or unitless chart values that reader cannot map.
COMPACT_PULSE = re.compile(
    r'(?<!\w)(?:P|PR|HR|pulse|heart[- ]rate)\s*(?:[=:]\s*)?(?:[<>≤≥~]\s*)?\d+(?:\.\d+)?\b',
    re.IGNORECASE)



def verified_sources(policy):
    sources = {}
    for row in policy['governing_criteria']:
        study = row['study']
        file = BENCH / 'round17/registry/benchmark_2015/xml' / (study + '.xml')
        raw = file.read_bytes()
        if sha256(raw).hexdigest() != row['registry_sha256']:
            raise ValueError('Registry source changed')
        doc = ET.fromstring(raw)
        text = ' '.join((doc.findtext(row['registry_locator']) or '').split())
        if (doc.findtext('id_info/nct_id') != study or not text
                or text.count(row['text']) != 1 or row['parent_rule'] not in text):
            raise ValueError('Registry source does not verify the reviewed passage')
        sources[(study, row['type'], row['text'])] = row
    return sources


def evaluate(resources, subject, pack, study, case, policy, sources, *, compact_rate_pattern=COMPACT_PULSE):
    trace = prescreen(resources, subject, pack, study, case)
    strict = trace['criteria'][case]['state']
    outcome = dict(subject=subject, study=study, case=case, strict=strict, exam_arm=strict,
                   source_sha256=trace['source_sha256'])
    rule = pack['rules'][case]
    source = rule['source']
    review = sources.get((study, source['criterion_type'], source['criterion_text']))
    if not review or rule['rule']['expression'] != review['predicate']:
        return outcome
    proofs = trace['research_prescreen']['proof']
    if len(proofs) != 1 or strict != 'MISSING_DATA':
        return outcome
    proof = proofs[0]
    if (proof['method'] != 'term_implies_lower_bound' or proof['sign'] != policy['term']
            or proof['fact'] != policy['fact'] or proof['assumed_open_lower_bound'] != policy['open_lower_bound']
            or rule['rule']['facts'][proof['fact']]['unit'] != policy['unit']):
        return outcome
    chart = NativeChart(resources, subject, pack['contracts'], study)
    document = next(r for r in resources if r['resourceType'] + '/' + r['id'] == chart.source)
    raw = base64.b64decode(document['content'][0]['attachment']['data'], validate=True).decode()
    if compact_rate_pattern.search(raw):
        outcome['term_withheld'] = 'An explicit vital-sign number needs reconciliation.'
        return outcome
    lines = raw.splitlines()
    citations = [{'resource': ref, 'lines': [{'line': n, 'text': lines[n]} for n in chart.refs[ref]]}
                 for ref in proof['resources']]
    outcome.update(exam_arm='MET', evidence={
        'document': chart.source, 'citations': citations, 'source_value': proof['sign'],
        'age_years': proof['age_years'], 'unit': policy['unit'],
        'definition': policy['definition'], 'open_lower_bound': proof['assumed_open_lower_bound'],
        'evidence_type': 'inferred lower bound', 'comparison': review['predicate'],
        'evaluation_scope': review['evaluation_scope'], 'criterion': review['text'],
        'registry_sha256': review['registry_sha256'], 'registry_locator': review['registry_locator'],
        'study_screening': 'not evaluated', 'study_screening_context': review['screening_context'],
        'study_screening_source': review['screening_source']})
    return outcome


def run(out):
    out.mkdir(parents=True, exist_ok=True)
    policy = read_json(HERE / 'term_contract.json')
    sources = verified_sources(policy)
    pack = verify(read_json(R11 / 'compiled.json'))
    predictions = []
    for a, subject, resources, hashes in frozen_assignments():
        row = evaluate(resources, subject, pack, a['study'], str(a['annotation_id']), policy, sources)
        if row['source_sha256'] != hashes[subject]:
            raise ValueError('Unexpected patient source')
        predictions.append(row)
    freeze = out / 'exam_predictions_before_reference.json'
    freeze.write_text(json.dumps(dict(policy=policy, catalog_sha256=pack['sha256'], rows=predictions), indent=2) + '\n')
    frozen_bytes = freeze.read_bytes()
    frozen_rows = json.loads(frozen_bytes)['rows']
    with (BENCH / 'round13/134_predictions.csv').open() as stream:
        references = {r['annotation']: r['reference'] for r in csv.DictReader(stream)}
    if len(frozen_rows) != 134 or {r['case'] for r in frozen_rows} != set(references):
        raise ValueError('Changed assignment population')
    result = dict(assignments=len(frozen_rows), physician_definitive=sum(r in DECISIVE for r in references.values()),
                  freeze_sha256=sha256(frozen_bytes).hexdigest(), changes=[])
    for arm in ['strict', 'exam_arm']:
        scored = [r for r in frozen_rows if r[arm] in DECISIVE]
        result[arm] = {
            'agreeing': sum(r[arm] == references[r['case']] for r in scored),
            'disagreeing_on_definitive': sum(references[r['case']] in DECISIVE and r[arm] != references[r['case']] for r in scored),
            'definitive_on_indeterminate': sum(references[r['case']] not in DECISIVE for r in scored)}
    result['changes'] = [{'case': r['case'], 'strict': r['strict'], 'exam_arm': r['exam_arm'],
                          'physician_reference': references[r['case']]} for r in frozen_rows if r['exam_arm'] != r['strict']]
    (out / 'score.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    print(json.dumps(run(parser.parse_args().out), indent=2))
