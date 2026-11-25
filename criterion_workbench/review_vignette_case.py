"""Evaluate one numbered benchmark vignette against a collection of reviewed rules."""
import argparse
import hashlib
import json
from pathlib import Path
from screen_vignette import evaluate_vignette

def review_case(patient, note, criteria):
    results,requests={},{}
    for item in criteria:
        study,cid=item['study'],item['id']
        if cid in results.setdefault(study,{}):
            raise ValueError('Duplicate criterion identifier in study.')
        verdict=evaluate_vignette(item['rule'],patient,study,item['criterion_text'],note)
        pending=list(verdict['requests'])
        if verdict['state']=='SOURCE_SCOPE_HOLD' and 'applies' not in item['rule']:
            expr=item['rule']['expression']
            while 'not' in expr:expr=expr['not']
            if 'hold' in expr:
                text=expr['hold']
                digest=hashlib.sha256(json.dumps([study,cid,item['criterion_text'],text],ensure_ascii=False).encode()).hexdigest()
                pending.append({'id':digest,'route':'protocol_review','request':text})
        for q in pending:
            summary=requests.setdefault(q['id'],dict(q,criteria=[]))
            summary['criteria'].append([study,cid])
        verdict['requests']=[q['id'] for q in pending]
        results[study][cid]=verdict
    return {'criteria':results,'requests':list(requests.values())}

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('case',type=Path)
    print(json.dumps(review_case(**json.loads(ap.parse_args().case.read_text())),indent=2))
