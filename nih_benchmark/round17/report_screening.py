"""Join frozen predictions to the audit ledger for reporting after screening."""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent


def make_report(pair_file, row_file, output):
    trials=json.loads(pair_file.read_text())
    with row_file.open() as f:
        original={int(r['case']):r for r in csv.DictReader(f)}
    ids=[i for p in trials['pair_results'] for i in p['assigned_criteria']]
    if len(ids) != len(set(ids)) or set(ids)!=set(original):
        raise ValueError("Trial assignments and criterion scorecard disagree")
    output.mkdir(parents=True,exist_ok=True)
    examples=[]
    open_rows=0
    open_definite_reference=0
    for p in trials['pair_results']:
        for i in p['assigned_criteria']:
            r=original[i]
            if p['study']!=r['study'] or p['subject'].split('/',1)[1]!=r['patient']:
                raise ValueError("Patient or study identity mismatch")
        if not p['decisive_findings']:
            continue
        for i in p['assigned_criteria']:
            row=original[i]
            if row['original_strict'] not in ('MET','NOT_MET'):
                open_rows+=1
                if row['physician_reference'] in ('MET','NOT_MET'):
                    open_definite_reference+=1
        for f in p['decisive_findings']:
            proof=f['receipt']
            if f['gate']=='registered_age_window':
                age,reg=proof['patient_age'],proof['registration']
                unit={'a':'years','mo':'months','d':'days'}[age['unit']]
                value=f"{age['value']} {unit}"
                limits='; '.join(name+' '+v for name,v in reg['bounds'].items())
                patient_source=age['excerpt']
                protocol_source=reg['url']
            else:
                value=str(proof['value_days'])+' days'
                limits=proof['protocol']['criterion_text']
                patient_source=' | '.join(span['quote'] for span in proof['source_spans'].values())
                protocol_source=proof['protocol']['registry_url']
            examples.append(dict(study=p['study'],patient=p['subject'],disposition=p['disposition'],
                                 reason=f['gate'],documented_value=value,protocol_requirement=limits,
                                 source_text=patient_source,protocol_url=protocol_source,
                                 associated_rows=', '.join(map(str,p['assigned_criteria']))))
    with (output/'study_decision_evidence.csv').open('w',newline='') as f:
        columns=['study','patient','disposition','reason','documented_value','protocol_requirement',
                 'source_text','protocol_url','associated_rows']
        writer=csv.DictWriter(f,fieldnames=columns)
        writer.writeheader()
        writer.writerows(examples)
    report={'patient_study_pairs':trials['patient_study_pairs'],'dispositions':trials['pair_dispositions'],
            'decisive_reasons':dict(Counter(r['reason'] for r in examples)),
            'unresolved_criterion_rows_in_ruled_out_pairs':open_rows,
            'of_these_rows_with_definitive_physician_reference':open_definite_reference}
    (output/'screening_impact.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pairs',type=Path,default=HERE/'results/trial_dispositions.json')
    p.add_argument('--scorecard',type=Path,default=HERE/'results/original/all_pairs.csv')
    p.add_argument('--out',type=Path,default=HERE/'results')
    args=p.parse_args()
    print(json.dumps(make_report(args.pairs,args.scorecard,args.out),indent=2))
