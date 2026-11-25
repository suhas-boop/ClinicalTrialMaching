"""Score sealed predictions against the publisher's evaluation rows. Requires duckdb only for parquet input."""
import argparse,ast,csv,json,hashlib
from pathlib import Path
from collections import Counter
import duckdb
from run import HERE, dump, table

GOLD={'included':'MET','not excluded':'MET','not included':'NOT_MET','excluded':'NOT_MET',
      'not applicable':'NOT_APPLICABLE','not enough information':'MISSING_DATA'}

def score(path,out):
    receipt=json.loads((out/'receipt.json').read_text())
    pred=list(csv.DictReader((out/'criterion_results.csv').open()))
    from run import fingerprint
    for r in pred:
        for k in ('annotation_id','note_reader_fact_count','total_required_fact_types'):r[k]=int(r[k])
        for k in ('requests','source_sentences','partial_sentences','checks'):r[k]=ast.literal_eval(r[k])
    if fingerprint(pred)!=receipt['prediction_sha256']:raise ValueError('Unsealed predictions')
    gold={i:(GOLD[s],ast.literal_eval(ids) if ids else []) for i,s,ids in
          duckdb.connect().execute("SELECT annotation_id,expert_eligibility,expert_sentences FROM read_parquet(?) WHERE NOT training",[str(path)]).fetchall()}
    if set(gold)!={r['annotation_id'] for r in pred}:raise ValueError('Evaluation split mismatch')
    binary={'MET','NOT_MET'}
    for row in pred:
        state,ids=gold[row['annotation_id']]
        row.update(expert_state=state,expert_sentences=ids,exact_outcome=state==row['patient_result'],
                   evidence_overlap=bool(set(ids)&set(row['source_sentences'])))
    decided=[r for r in pred if r['patient_result'] in binary]
    receipt.update(publisher_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),publisher_definite=sum(r['expert_state'] in binary for r in pred),
                   pipeline_definite=len(decided),agreed_definite=sum(r['exact_outcome'] for r in decided),
                   decided_with_citation_overlap=sum(r['evidence_overlap'] for r in decided),
                   states_vs_expert={s:dict(Counter(r['patient_result'] for r in pred if r['expert_state']==s)) for s in sorted(set(GOLD.values()))})
    table(out/'scored_cases.csv',pred);dump(out/'scoring.json',receipt);print(json.dumps(receipt,indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('parquet',type=Path);p.add_argument('--out',type=Path,default=HERE/'results')
    args=p.parse_args();score(args.parquet,args.out)
