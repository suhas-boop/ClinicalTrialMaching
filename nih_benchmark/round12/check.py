import json
import csv
import hashlib
from pathlib import Path
from intake import plain_chart, HERE, R9
from screen import R11, read_json, verify, screen
from native import NativeChart
def main(panel='eval_cases',strict=True):
    pack=verify(read_json(R11/'compiled.json')); rows=[]
    for n,line in enumerate((HERE/(panel+'.jsonl')).read_text().splitlines(),1):
        case=json.loads(line)
        b,links=plain_chart('test',case['text'],'2026-01-01T00:00:00Z')
        items=[e['resource'] for e in b['entry']]
        snap=NativeChart(items,'Patient/test',pack['contracts'],case.get('study'))
        got={}
        for c in pack['contracts'].values():
            val,issue,refs,_=snap.read(c['spec'])
            if issue is None:got[c['spec']['label']]=val
        if any(case['text'][s['start']:s['end']]!=s['excerpt'] for s in links):raise AssertionError(n)
        rows.append({'case':n,'text':case['text'],'expected':case['want'],'observed':got,'passed':got==case['want']})
    (HERE/'results').mkdir(exist_ok=True)
    (HERE/'results'/(panel+'_results.json')).write_text(json.dumps(rows,indent=2)+'\n')
    for r in rows:
        if not r['passed']:print(r)
    print('Exact cases:',sum(r['passed'] for r in rows),'/',len(rows))
    if strict:assert all(r['passed'] for r in rows)
if __name__=='__main__':
    main();main('transfer_cases',False)
