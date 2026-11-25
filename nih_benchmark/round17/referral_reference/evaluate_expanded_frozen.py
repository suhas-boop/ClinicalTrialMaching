"""Post-freeze referral comparison of the other subject–study combinations, using original SIGIR grades."""
import argparse
import csv
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
PREDICTIONS='02781f9bc54d1ffd2b4f62799d116edcf02db91d7988628a25994790235db865'
IDENTITIES='71b5272e3fac79f17fced1433c3f017a58bb3c73ca025cf2240ee7a469c0c88d'
QRELS='f0b9aa8aa22b4c4eb5405c0bd2dc8220ac43a9c1d75e08782a410324270ce45e'
GRADES=('0','1','2','UNJUDGED')

def read_frozen(path,expected):
    content=path.read_bytes()
    if sha256(content).hexdigest()!=expected: raise ValueError('Frozen artifact changed: '+path.name)
    return content.decode().splitlines()

def compare(predictions,reference,qrels,out):
    original=list(csv.DictReader(read_frozen(reference,IDENTITIES)))
    preds=list(csv.DictReader(read_frozen(predictions,PREDICTIONS)))
    identities={}
    for r in original:
        identity=(r['original_topic_id'],r['frozen_note_sha256'])
        if identities.setdefault(r['patient'],identity)!=identity:
            raise ValueError('Ambiguous patient identity')
    excluded={(r['patient'],r['study']) for r in original}
    studies={r['study'] for r in original}
    expected={(pid,study) for pid in identities for study in studies}-excluded
    keys={(r['patient'],r['study']) for r in preds}
    if len(original)!=68 or len(identities)!=44 or len(studies)!=68 or len(preds)!=len(keys) or keys!=expected:
        raise ValueError('Frozen expanded population differs from the verified disjoint cohort')
    labels={}
    for line,raw in enumerate(read_frozen(qrels,QRELS),1):
        topic,iteration,trial,grade=raw.split()
        if iteration!='0' or grade not in GRADES[:3] or (topic,trial) in labels:
            raise ValueError('Unexpected original judgment')
        labels[(topic,trial)]=(grade,line)
    counts={}
    age_disagreements=[]
    gate_counts=Counter()
    age_reasons=Counter()
    judged=[]
    for row in preds:
        pid=row['patient'];study=row['study'];disp=row['disposition']
        topic,source=identities[pid]
        if row['source_sha256']!=source or row['subject'].split('/',1)[1]!=pid:
            raise ValueError('Patient or source mismatch')
        grade,line=labels.get((topic,study),('UNJUDGED',None))
        counts.setdefault(disp,Counter())[grade]+=1
        if disp=='NOT_ELIGIBLE_AT_PRESENTATION':
            gate_counts[row['decisive_gates']]+=1
            age_reasons[row['age_reason']]+=1
        if grade=='2' and 'registered_age_window' in row['decisive_gates']:
            age_disagreements.append(dict(patient=pid,study=study,gate=row['decisive_gates'],reason=row['age_reason']))
        if grade!='UNJUDGED':
            judged.append(dict(patient=pid,subject=row['subject'],study=study,topic=topic,pocketmd_disposition=disp,
                               decisive_gates=row['decisive_gates'],age_reason=row['age_reason'],
                               csiro_referral_grade=grade,csiro_qrels_line=line))
    def ordered(c):return {grade:c[grade] for grade in GRADES}
    receipt=dict(predictions_file_sha256=PREDICTIONS,original_topic_join_sha256=IDENTITIES,published_qrels_sha256=QRELS,
                 qrels_doi='https://doi.org/10.4225/08/58e2e83d92c2b',
                 qrels_source='https://data.csiro.au/dap/ws/v2/collections/22333/data/49692372',
                 subject_source_hashes_verified=len(identities),studies=len(studies),original_68_overlap=len(keys&excluded),
                 new_patient_study_pairs=len(keys),judged=len(judged),unjudged=len(keys)-len(judged),
                 grade_key={'0':'would decline referral','1':'consider referral after further investigation',
                            '2':'highly likely to refer','UNJUDGED':'no published judgment'},
                 grade_counts=ordered(sum(counts.values(),Counter())),
                 grades_by_pocketmd_disposition={d:ordered(c) for d,c in sorted(counts.items())},
                 exclusion_gates=dict(gate_counts),excluded_age_reasons=dict(age_reasons),
                 highly_likely_referral_with_age_exclusion=age_disagreements,
                 interpretation='All newly excluded pairs lacked a published referral judgment. No independent trial-level assessment of those exclusions is available in this collection. Continuing screening asks for further evaluation. A non-referral grade measures referral preference.')
    out.mkdir(parents=True,exist_ok=True)
    with (out/'expanded_judged_pairs.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(judged[0]));w.writeheader();w.writerows(judged)
    (out/'expanded_referral_results.json').write_text(json.dumps(receipt,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--predictions',type=Path,default=HERE.parent/'results/expanded_predictions.csv')
    p.add_argument('--reference',type=Path,default=HERE/'sigir_referral_reference.csv')
    p.add_argument('--qrels',type=Path,default=HERE/'v4_qrels-clinical_trials.txt')
    p.add_argument('--out',type=Path,default=HERE)
    a=p.parse_args();compare(a.predictions,a.reference,a.qrels,a.out)
