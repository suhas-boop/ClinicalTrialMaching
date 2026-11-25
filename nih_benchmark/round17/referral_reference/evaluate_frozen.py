"""Join the frozen study dispositions to independent SIGIR referral judgments after prediction."""
import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
HERE=Path(__file__).resolve().parent
PREDICTION_SHA256='bde5ccd5104332851d4772ecedeb0aedd5a095df26632f64cdb8cdee5fb350ff'
REFERENCE_SHA256='71b5272e3fac79f17fced1433c3f017a58bb3c73ca025cf2240ee7a469c0c88d'

def read_pinned(p,digest):
    data=p.read_bytes()
    if hashlib.sha256(data).hexdigest()!=digest: raise ValueError('Frozen artifact hash mismatch: '+p.name)
    return data.decode()

def run(predictions,reference,out):
    ensemble=json.loads(read_pinned(predictions,PREDICTION_SHA256))['pair_results']
    published=list(csv.DictReader(read_pinned(reference,REFERENCE_SHA256).splitlines()))
    rows={(r['patient'],r['study']):r for r in published}
    keys=[(r['subject'].split('/')[1],r['study']) for r in ensemble]
    if len(ensemble)!=len(published) or len(rows)!=len(keys) or len(set(keys))!=len(keys) or set(keys)!=rows.keys():
        raise ValueError('Unexpected, missing or duplicate patient–study pairs')
    histogram={}
    output=[]
    for k,pred in zip(keys,ensemble):
        ref=rows[k]
        grade=ref['csiro_referral_grade'] or 'UNJUDGED'
        histogram.setdefault(pred['disposition'],Counter())[grade]+=1
        output.append(dict(patient=k[0],study=k[1],subject_type=pred['subject'].split('/')[0],
                           pocketmd_disposition=pred['disposition'],
                           decisive_gate='|'.join(e['gate'] for e in pred['decisive_findings']),
                           csiro_referral_grade=ref['csiro_referral_grade'],csiro_grade_meaning=ref['csiro_grade_meaning'],
                           csiro_qrels_line=ref['csiro_qrels_line'],
                           csiro_study_source=ref['csiro_source'],nih_release_grade=ref['nih_release_grade']))
    def counts(c):
        return {g:c[g] for g in ['0','1','2','UNJUDGED']}
    grade2=[dict(patient=r['patient'],study=r['study'],gate=r['decisive_gate']) for r in output
            if r['pocketmd_disposition']=='NOT_ELIGIBLE_AT_PRESENTATION' and r['csiro_referral_grade']=='2']
    receipt=dict(prediction_sha256=PREDICTION_SHA256,reference_sha256=REFERENCE_SHA256,pairs=len(output),
                 counts_by_disposition={k:counts(v) for k,v in sorted(histogram.items())},
                 total_referral_grades=counts(sum(histogram.values(),Counter())),
                 excluded_despite_high_referral=grade2,
                 interpretation='Screening dispositions and medical assessor referral judgments answer different questions. The selected cases lack a grade-zero non-referral comparator. These numbers do not estimate clinical eligibility accuracy or specificity.')
    out.mkdir(parents=True,exist_ok=True)
    with (out/'trial_referral_comparison.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(output[0]));w.writeheader();w.writerows(output)
    (out/'trial_referral_results.json').write_text(json.dumps(receipt,indent=2)+'\n')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--predictions',required=True,type=Path)
    parser.add_argument('--reference',default=HERE/'sigir_referral_reference.csv',type=Path)
    parser.add_argument('--out',default=HERE,type=Path)
    a=parser.parse_args();run(a.predictions,a.reference,a.out)
