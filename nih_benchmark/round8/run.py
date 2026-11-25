"""Run all publisher-designated evaluation examples. This module never opens the gold label file."""
import argparse
import base64
from collections import Counter
from copy import deepcopy
import csv
from hashlib import sha256
import json
from pathlib import Path
import sys
from author_rules import build, HERE, DATA
from bindings import contract,make_packet,ref
from evidence_review import screen
from note_adapter import abstract,admits

def fingerprint(x):
    return sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def dump(path,obj):
    path.write_text(json.dumps(obj,indent=2,sort_keys=True,ensure_ascii=False)+'\n')
def table(path,rows):
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)

def packet(rules,study,version,pid,known,note):
    normalized={}
    for cid,r in rules.items():
        normalized[cid]={k:known[k][0] for k,s in r['facts'].items() if k in known and admits(k,s)}
    visit='screen-'+fingerprint([pid,study,version])[:24]
    p=make_packet(rules,normalized,study,version,patient=pid,encounter=visit)
    if abstract(note)[1]:
        p['context']['source_scope']='multiple_subjects'
        p['context']['source_sha256']=sha256(note.encode()).hexdigest()
    # The benchmark lacks actual study encounter dates. All resources share a clearly
    # identified synthetic encounter. No date comparison is inferred from that timestamp.
    lines=dict(x.split('. ',1) for x in note.splitlines())
    index={}
    for cid,facts in normalized.items():
        for key in facts:
            spec=rules[cid]['facts'][key]; code=contract(spec)
            index['src-'+code]=(key,known[key][1])
    references={}
    renamed={}
    for e in p['bundle']['entry']:
        d=e['resource']
        if d['resourceType'] in {'Observation','DocumentReference'}:
            old_ref=ref(d)
            original=d['id']
            d['id']=d['resourceType'][:3].lower()+'-'+fingerprint([pid,visit,original])[:32]
            renamed[old_ref]=ref(d)
            if d['resourceType']=='DocumentReference':
                index[d['id']]=index[original]
                d['context']={'encounter':[{'reference':'Encounter/'+visit}],
                              'related':[{'reference':'Condition/index-'+pid}]}
    for e in p['bundle']['entry']:
        for link in e['resource'].get('derivedFrom',[]):
            link['reference']=renamed[link['reference']]
    for e in p['bundle']['entry']:
        d=e['resource']
        if d['resourceType']=='DocumentReference':
            key,ids=index[d['id']]
            references[ref(d)]=ids
            d['content'][0]['attachment'].update(title=f'{pid} | sentences {ids}',
               data=base64.b64encode('\n'.join(lines[str(i)] for i in ids).encode()).decode())
    return p,references

def values(node,want):
    """Construct a synthetic witness satisfying or violating an expression independently of the implementation."""
    if 'fact' in node:
        if 'op' not in node:return {node['fact']:want}
        op,t=node['op'],node['value']
        options={'lt':(t-1,t),'gt':(t+1,t),'le':(t,t+1),'ge':(t,t-1),'eq':(t,t+1)}
        return {node['fact']:options[op][0 if want else 1]}
    if 'not' in node:return values(node['not'],not want)
    group=node.get('all',node.get('any',node.get('same_measurement')))
    if group is None:raise ValueError(node)
    result={}
    for child in group:
        for k,v in values(child,want).items():
            if k in result and result[k]!=v:raise ValueError('Scenario has contradictory assignments')
            result[k]=v
    return result

def controls(cid,r,study,ver):
    req={cid:r}
    def run(vals,expected):
        p=make_packet(req,{cid:vals},study,ver)
        out=screen(req,p,study,ver)['criteria'][cid]
        if out['state']!=expected or (expected in ('MET','NOT_MET','NOT_APPLICABLE') and not out['evidence']):
            raise ValueError((cid,expected,out))
    if 'hold' in r['expression']:
        run({},'AUTHORING_HOLD');return ['authoring hold']
    checks=[]
    gate=values(r['applies'],True) if 'applies' in r else {}
    for want in (True,False):
        full=values(r['expression'],want)|gate
        exp='MET' if want else 'NOT_MET'
        run(full,exp);checks.append(exp)
    if 'applies' in r:
        run(values(r['applies'],False),'NOT_APPLICABLE');checks.append('NOT_APPLICABLE')
    out=screen(req,make_packet(req,{},study,ver),study,ver)['criteria'][cid]
    if out['evidence'] or out['state'] not in {'MISSING_DATA','PATIENT_SURVEY','INVESTIGATOR_ACTIONS','STUDY_ACTION'}:
        raise ValueError(('empty',cid,out))
    checks.append('empty evidence');return checks

def load_cases():
    return sorted([r for f in (DATA,DATA/'round2',DATA/'round3') for r in json.loads((f/'blind.json').read_text())],key=lambda r:r['annotation_id'])

def run(destination):
    dest=Path(destination);dest.mkdir(parents=True,exist_ok=True)
    cases=load_cases();pack=build()
    membership=[(r['annotation_id'],r['patient_id'],r['trial_id'],r['criterion_type'],r['criterion_text'],r['note']) for r in cases]
    if len(cases)!=134 or fingerprint(membership)!=(HERE/'membership.sha256').read_text().strip():
        raise ValueError('Input mismatch with publisher evaluation split')
    studies={}
    for cid,entry in pack.items():
        studies.setdefault(entry['source']['trial_id'],{})[cid]=entry
    versions={study:fingerprint(reg) for study,reg in studies.items()}
    audit=[]; abstractions={};catalog={};tasks={};packets={};traces={};test_log={}
    for row in cases:
        cid=str(row['annotation_id']);p=row['patient_id'];study=row['trial_id']
        rule=pack[cid]['rule'];keys={cid:rule};v=versions[study]
        tests=controls(cid,rule,study,v);test_log[cid]=tests
        held='authoring hold' in tests
        known,group=abstract(row['note']);packet_id=study+'/'+p
        abstractions[p]={'source_sha256':sha256(row['note'].encode()).hexdigest(),'scope':'multiple_subjects' if group else 'individual',
                         'facts':{k:{'value':v,'sentence_ids':ids} for k,(v,ids) in known.items()}}
        for key,spec in rule['facts'].items():
            k=contract(spec)
            catalog.setdefault(k,dict(fact=key,role=spec['role'],kind=spec['kind'],unit=spec.get('unit',''),
                scope=spec['scope'],normalized_selector='Observation.code.coding.system + protocol version + code '+k,
                source_link='Observation.derivedFrom -> current versioned DocumentReference',note_reader=admits(key,spec)))
        if packet_id not in packets:
            rs={str(c['annotation_id']):pack[str(c['annotation_id'])]['rule'] for c in cases if c['patient_id']==p and c['trial_id']==study}
            packets[packet_id]=packet(rs,study,v,p,known,row['note'])
        fhir,refs=packets[packet_id]
        got=screen(keys,fhir,study,v)
        verdict=got['criteria'][cid];state=verdict['state']
        request_list=got['requests']
        ids=[]
        for q in request_list:
            ident=q['id'];ids.append(ident)
            if ident not in tasks:
                tasks[ident]=dict(route=q['route'],question_or_evidence=q['request'],patient='' if q['route']=='protocol_review' else p,
                                  studies=set(),criteria=set())
            tasks[ident]['studies'].add(study);tasks[ident]['criteria'].add(cid)
        source_ids=sorted({i for k in verdict['evidence'] for i in refs.get(k,[])})
        partial=sorted({i for k in verdict['partial_evidence'] for i in refs.get(k,[])})
        if state in ('MET','NOT_MET') and not source_ids:raise ValueError('Unattributed decision')
        record=dict(annotation_id=int(cid),study=study,patient=p,criterion=row['criterion_text'],rule_status='CLINICIAN_INPUT' if held else 'EXECUTABLE_NORMALIZED_FHIR',
                    patient_result=state,source_sentences=source_ids,partial_sentences=partial,protocol_fingerprint=v,
                    input_packet=packet_id,note_reader_fact_count=sum(admits(k,s) for k,s in rule['facts'].items()),
                    total_required_fact_types=len(rule['facts']),requests=ids,checks=tests)
        audit.append(record);traces[cid]=dict(verdict=verdict if not group or held else {'state':state,'evidence':[]},requests=ids)
    if len(audit)!=len(pack) or any(t['route']=='engineering' for t in tasks.values()):raise ValueError('Incomplete engineering coverage')
    task_rows=[dict(id=k,route=t['route'],patient=t['patient'],studies=','.join(sorted(t['studies'])),
                    criteria=','.join(sorted(t['criteria'],key=int)),question_or_evidence=t['question_or_evidence']) for k,t in sorted(tasks.items())]
    dump(dest/'patient_evidence.json',abstractions);table(dest/'evidence_catalog.csv',[dict(contract=k,**c) for k,c in sorted(catalog.items())]);
    table(dest/'routing.csv',task_rows);table(dest/'criterion_results.csv',audit)
    dump(dest/'rules.json',pack);dump(dest/'traces.json',traces);dump(dest/'controls.json',test_log)
    dump(dest/'patient_packets.json',{k:v[0] for k,v in packets.items()})
    receipt=dict(rows=len(audit),patients=len({r['patient'] for r in audit}),trials=len(studies),
                 rule_status=Counter(r['rule_status'] for r in audit),patient_result=Counter(r['patient_result'] for r in audit),
                 distinct_tasks=Counter(r['route'] for r in task_rows),control_runs=sum(map(len,test_log.values())),
                 rule_pack_sha256=fingerprint(pack),prediction_sha256=fingerprint(audit))
    dump(dest/'receipt.json',receipt);print(json.dumps(receipt,indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=HERE/'results')
    run(p.parse_args().out)
