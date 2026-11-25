"""Paired TrialGPT replay: evidence policies are opt-in, not clinical authority."""
import argparse
from collections import Counter
from hashlib import sha256
import json
import re
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
sys.path.insert(0, str(BENCH / 'round21'))
from user_clarified import replay, R11, read_json, verify, frozen_assignments
from literal_scope import screen_synthetic_note
from respiratory import predict as exam_predict

PUBLISHER = BENCH / 'round8/publisher/annotations.parquet'
SOURCE = '14c547184fac9b013cd17441fd028845b40150c76b022e58334f5494077e5234'
LABEL = {'included':'MET','not excluded':'MET','not included':'NOT_MET',
         'excluded':'NOT_MET','not enough information':'MISSING_DATA','not applicable':'NOT_APPLICABLE'}
DEFINITE = {'MET','NOT_MET'}

def safe_ref(ref):
    return re.sub(r'^DocumentReference/[^#]+', 'DocumentReference/pinned-public-note', ref)
EXPECTED = {'literal_synthetic_cohort':{'322'}, 'supported_exam':{'186'}, 'user_interpretation':{'706'}}

def phase1(out):
    import duckdb
    if sha256(PUBLISHER.read_bytes()).hexdigest() != SOURCE:
        raise ValueError('Public publisher package differs')
    published = duckdb.connect().execute("""SELECT annotation_id,patient_id,note,trial_id,criterion_type,criterion_text
            FROM read_parquet(?) WHERE NOT training ORDER BY annotation_id""",[str(PUBLISHER)]).fetchall()
    notes = read_json(BENCH / 'round9/notes.json')
    pack = verify(read_json(R11/'compiled.json'))
    answer = read_json(BENCH/'round21/user_answer.json')
    proof = {}
    prior = replay(answer)
    exam_proofs={r['case']:r for r in exam_predict()['rows']}
    existing = {row['case']:row for row in prior['rows']}
    assert len(published)==len(existing)==134
    assert {str(row[0]) for row in published}==set(existing)
    checked = {}
    for case, subject, note, study, kind, criterion in published:
        case=str(case)
        src=pack['rules'][case]['source']
        row=existing[case]
        assert (study,kind,criterion)==(src['trial_id'],src['criterion_type'],src['criterion_text'])
        assert (study,sha256(note.encode()).hexdigest())==(row['study'],row['source_sha256'])
        assert notes[subject]==note
        checked[case]=(subject,study)
    rows=[]
    changes={p:set() for p in EXPECTED}
    for a, subject, resources, hashes in frozen_assignments():
        case,study = str(a['annotation_id']),a['study']
        assert checked[case]==(a['patient'],study) and subject.rsplit('/',1)[-1]==a['patient']
        r=existing[case]
        cohort=screen_synthetic_note(resources,subject,pack,study,case,hashes)
        strict=cohort['strict_state']
        assert strict==r['strict']
        assert hashes[subject]==r['source_sha256']==cohort['trace']['source_sha256']
        states={'literal_synthetic_cohort':cohort['trace']['criteria'][case]['state'],
                'supported_exam':r['supported_exam'],'user_interpretation':r['strict_plus_user']}
        live=[k for k,v in states.items() if v!=strict]
        if len(live)>1:
            raise ValueError('Overlapping policy changes require reconciliation')
        if live:
            policy=live[0]
            if states[policy] not in DEFINITE or strict in DEFINITE:
                raise ValueError('Unexpected decisive conflict')
            changes[policy].add(case)
            if policy=='literal_synthetic_cohort':
                p=cohort['trace']['criteria'][case]
                proof[case]={'policy':policy,'lines':p['source_sentences'],'resources':[safe_ref(ref) for ref in p['evidence']],
                             'condition':'literal adult descriptor, frozen public vignettes only'}
            if policy=='supported_exam':
                e=exam_proofs[case]['evidence']
                proof[case]={'policy':policy,'lines':sorted({l['line'] for c in e['citations'] for l in c['lines']}),
                             'resources':[c['resource'] for c in e['citations']],
                             'condition':'numeric lower bound inferred by optional examination terminology policy'}
            if policy=='user_interpretation':
                p=r['clarification_trace']['criteria'][case]
                proof[case]={'policy':policy,'lines':p['source_sentences'],'resources':[safe_ref(ref) for ref in p['evidence']],
                             'condition':'user interpretation only; no governing sponsor clause verified'}
            assert proof[case]['lines'] and proof[case]['resources']
        rows.append({'annotation':case,'study':study,'public_note_sha256':r['source_sha256'],'strict':strict,
                     **states,'literal_plus_exam':states[live[0]] if live and live[0] != 'user_interpretation' else strict,
                     'exam_plus_user':r['exam_plus_user'],'combined_experimental':states[live[0]] if live else strict})
    if changes!=EXPECTED:
        raise ValueError('Unexpected patch overlap or changes: '+str(changes))
    out.mkdir(parents=True,exist_ok=False)
    artifact={'rows':rows,'proof':proof,'publisher_sha256':SOURCE,'catalog_fingerprint':pack['sha256']}
    freeze=out/'predictions_before_labels.json'
    freeze.write_text(json.dumps(artifact,sort_keys=True,indent=2)+'\n')
    return freeze

def phase2(freeze):
    import duckdb
    frozen=freeze.read_bytes();artifact=json.loads(frozen);rows=artifact['rows']
    labels={str(i):LABEL[v] for i,v in duckdb.connect().execute(
        "SELECT annotation_id,expert_eligibility FROM read_parquet(?) WHERE NOT training",[str(PUBLISHER)]).fetchall()}
    assert set(labels)=={r['annotation'] for r in rows}
    arm_names=['strict','literal_synthetic_cohort','supported_exam','user_interpretation',
               'literal_plus_exam','exam_plus_user','combined_experimental']
    arms={}
    for arm in arm_names:
        agrees=wrong=indeterminate=0;pending=Counter()
        for r in rows:
            gold=labels[r['annotation']]; verdict=r[arm]
            if gold in DEFINITE:
                if verdict==gold:agrees+=1
                elif verdict in DEFINITE:wrong+=1
                else:pending[verdict]+=1
            elif verdict in DEFINITE:indeterminate+=1
        arms[arm]=dict(agreeing=agrees,wrong_definitive=wrong,
                       definitive_on_indeterminate=indeterminate,pending=dict(pending))
    assert all(not a['wrong_definitive'] and not a['definitive_on_indeterminate'] for a in arms.values())
    return dict(pairs=len(rows),definitive_reference=sum(v in DEFINITE for v in labels.values()),
                prediction_sha256=sha256(frozen).hexdigest(),arms=arms,changed_cases=artifact['proof'])

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('out',type=Path)
    freeze=phase1(p.parse_args().out)
    score=phase2(freeze)
    (freeze.parent/'summary.json').write_text(json.dumps(score,indent=2)+'\n')
    print(json.dumps(score,indent=2))
