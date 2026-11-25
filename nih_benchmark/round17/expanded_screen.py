"""Blind study gate screening of all unassigned combinations of the frozen subjects and studies."""
import argparse
import csv
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
from xml.etree import ElementTree as ET

import fever_gate
import study_scope
from trial_disposition import disposition

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent


def digest(data):
    return sha256(data).hexdigest()


def file_hash(path):
    return digest(path.read_bytes())


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)+'\n')


def archived_fever_source():
    """Confirm the same obligatory clause is present in the benchmark-era registry."""
    xml = study_scope.ORIGINALS / 'xml' / (fever_gate.STUDY + '.xml')
    raw = xml.read_bytes()
    expected = '5ecf4469adaded673ddc407fc80a59752adc30c76835c05d521d9b0a33d00099'
    if digest(raw) != expected:
        raise ValueError('Unverified archived fever registration')
    record = ET.fromstring(raw)
    text = record.findtext('eligibility/criteria/textblock')
    if (record.findtext('id_info/nct_id') != fever_gate.STUDY
            or not re.match(r'^\s*Inclusion Criteria:\s*-\s*'+re.escape(fever_gate.TEXT)+r'\s*\n',text)):
        raise ValueError('Fever duration item unavailable in the archived inclusion list')
    return dict(study=fever_gate.STUDY, xml_sha256=expected, locator='eligibility/criteria/textblock / inclusion item 1',
                text=fever_gate.TEXT)


def run(out):
    pack = study_scope.verify(study_scope.read_json(study_scope.DEFAULT_CATALOG))
    assignment_path = BENCH/'round9/assignments.json'
    assignments = study_scope.read_json(assignment_path)
    original_pairs = {(r['patient'],r['study']) for r in assignments}
    names = sorted({p for p,s in original_pairs})
    studies = sorted({s for p,s in original_pairs})
    if ({str(r['annotation_id']) for r in assignments} != set(pack['rules'])
            or any(pack['rules'][str(r['annotation_id'])]['source']['trial_id'] != r['study'] for r in assignments)):
        raise ValueError('Assignment and catalog mismatch')
    archived_fever = archived_fever_source()
    export = BENCH/'round12/export'
    subjects = {s['case']:s['subject'] for s in study_scope.read_json(export/'cases.json')}
    expected = study_scope.read_json(BENCH/'round9/note_hashes.json')
    out.mkdir(parents=True,exist_ok=True)
    gate_counts, age_states, age_reasons, fever_states, dispositions = (Counter() for _ in range(5))
    patient_sources, trial_sources = {}, {}
    rows = []
    for pid in names:
        subject = subjects[pid]
        path = export/'bundles'/(pid+'.json')
        resources = [e['resource'] for e in study_scope.read_json(path)['entry']]
        patient_sources[subject] = dict(bundle_sha256=file_hash(path), source_sha256=expected[pid])
        for study in studies:
            if (pid,study) in original_pairs:
                continue
            age = study_scope.assess(resources, subject, study, pack, expected_hash=expected[pid])
            fever = fever_gate.screen_fever(resources, subject, study, expected_source_sha256=expected[pid])
            result = disposition(age,fever)
            gates = sorted(x['gate'] for x in result['decisive_findings'])
            gate_counts.update(gates)
            age_states[age['state']]+=1
            age_reasons[age['reason']]+=1
            fever_state=fever['state'] if fever else ''
            fever_states[fever_state or 'GATE_NOT_DEFINED_FOR_STUDY']+=1
            dispositions[result['disposition']]+=1
            registry=age['registration']
            if registry:
                xml_digest = registry['sha256']
                if trial_sources.setdefault(study,xml_digest)!=xml_digest:
                    raise ValueError('Archived source changed during expanded screening')
            else:
                xml_digest = ''
            verified_age=age['patient_age'] or {}
            refs = (verified_age.get('resources',[]) if 'registered_age_window' in gates else []) + (
                fever['evidence'] if 'required_fever_duration' in gates else [])
            if gates and (not refs or (not xml_digest and 'registered_age_window' in gates)):
                raise ValueError('Definitive study exclusion lacks its evidence trace')
            rows.append(dict(patient=pid,subject=subject,study=study,disposition=result['disposition'],
                             decisive_gates='|'.join(gates),age_state=age['state'],age_reason=age['reason'],
                             fever_state=fever_state,source_sha256=expected[pid],registration_sha256=xml_digest,
                             cited_refs='|'.join(refs)))
    if len(rows)!=len(names)*len(studies)-len(original_pairs) or len({(r['patient'],r['study']) for r in rows})!=len(rows):
        raise ValueError('Expanded assignment set changed')
    predictions=out/'expanded_predictions.csv'
    with predictions.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=rows[0],lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    sources=dict(assignment_sha256=file_hash(assignment_path), catalog_sha256=pack['sha256'],
                 patient_sources=patient_sources, archived_registry_manifest_sha256=study_scope.MANIFEST_SHA256,
                 registry_xml_sha256=trial_sources, fever_gate_registry_sha256=fever_gate.DIGEST,
                 benchmark_era_fever_gate=archived_fever)
    source_file=out/'expanded_sources.json'
    write_json(source_file,sources)
    summary = dict(assigned_subjects=len(names), assigned_studies=len(studies), original_assignments=len(assignments),
                   original_pairs_excluded=len(original_pairs), expanded_pairs=len(rows), group_subjects=sum(
                   s.startswith('Group/') for s in patient_sources), dispositions=dict(dispositions),
                   decisive_gate_counts=dict(gate_counts), age_states=dict(age_states), age_reasons=dict(age_reasons),
                   fever_states=dict(fever_states), predictions_sha256=file_hash(predictions), sources_sha256=file_hash(source_file),
                   code_sha256={f:file_hash(HERE/f) for f in ('expanded_screen.py','study_scope.py','fever_gate.py','trial_disposition.py')},
                   scope='Read only frozen assignments, source charts, rules and registrations. Continue screening means no exclusion established by the implemented gates.')
    write_json(out/'expanded_summary.json',summary)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=HERE/'results')
    args=parser.parse_args()
    print(json.dumps(run(args.out),indent=2))
