"""Stress the real FHIR screening interface with mixed Boolean branches, comparisons, exclusions and source isolation."""
from copy import deepcopy
from itertools import product
from pathlib import Path
import json,operator,sys
from run import HERE,build,fingerprint,dump,make_packet,values,screen

OPS={'eq':operator.eq,'lt':operator.lt,'gt':operator.gt,'ge':operator.ge,'le':operator.le}
def expected(n,facts):
    if 'not' in n:
        answer=expected(n['not'],facts)
        return None if answer is None else not answer
    if 'same_measurement' in n:
        outcomes={expected(form,facts) for form in n['same_measurement']}
        return outcomes.pop() if len(outcomes)==1 else None
    if 'all' in n:return all(expected(x,facts) for x in n['all'])
    if 'any' in n:return any(expected(x,facts) for x in n['any'])
    return OPS[n.get('op','eq')](facts[n['fact']],n.get('value',True))

def validate_all(out):
    pack=build();checks={}
    for cid,e in pack.items():
        r=e['rule'];study=e['source']['trial_id'];v=fingerprint(r);rules={cid:r}
        if 'hold' in r['expression']:continue
        domains={}
        for node in [r['expression']]+([r['applies']] if 'applies' in r else []):
            for key,yes in values(node,True).items():
                no=values(node,False)[key];domains[key]=[yes,no]
        def run(vals,want,mutator=None):
            p=make_packet(rules,{cid:vals},study,v)
            if mutator:mutator(p)
            got=screen(rules,p,study,v)['criteria'][cid]
            if got['state']!=want:raise AssertionError((cid,vals,got['state'],want))
            return got
        keys=list(domains)
        if len(keys)<=7:
            inputs=[dict(zip(keys,t)) for t in product(*(domains[k] for k in keys))]
        else:
            # Include both decision extremes and one-variable changes around both.
            inputs=[]
            for b in (0,1):
                base={k:domains[k][b] for k in keys}
                inputs.extend([base]+[dict(base,**{k:domains[k][1-b]}) for k in keys])
        for vals in inputs:
            verdict=expected(r['expression'],vals)
            want='NOT_APPLICABLE' if 'applies' in r and not expected(r['applies'],vals) else {True:'MET',False:'NOT_MET',None:'MISSING_DATA'}[verdict]
            got=run(vals,want)
            if not got['evidence']:raise AssertionError('Unattributed decision')
        checks[cid]=len(inputs)
    dump(out/'mixed_branch_checks.json',checks)
    print('Mixed assignment checks',sum(checks.values()),'rules',len(checks))
if __name__=='__main__':validate_all(HERE/'results')
