"""Replay retrieval on the frozen record-retrieval stratum. Physician citations enter only the final scoring pass."""
import ast
import base64
from collections import Counter
from contextlib import closing
import csv
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
DATA = HERE.parent
sys.path.insert(0, str(DATA))
from review_replay import make_packet, contract, roles
from narrative_evidence import extract, supports
from record_search import add_document, connect, retrieve, search

def load(path):
    return json.loads(path.read_text())

def digest(b):
    return hashlib.sha256(b).hexdigest()

def texts(case, topics):
    pid=case['patient_id']
    year,num=re.fullmatch(r'sigir-(201[45])(\d+)',pid).groups()
    topic=next(t for t in topics[year] if int(t.attrib['number'])==int(num))
    numbered=[(n,s) for n,s in re.findall(r'^(\d+)\. (.*)$',case['note'],re.M)]
    result={'NIH vignette':numbered}
    for name in ('description','summary'):
        value=' '.join(topic.findtext(name).split())
        result['TREC '+name]=[(str(i),s) for i,s in enumerate(re.split(r'(?<=[.?!])\s+(?=[A-Z])',value))]
    return result

def packet(folder,rows,case,rule,known):
    cid=str(case['annotation_id'])
    if folder.name=='round3':
        fingerprint=json.dumps([case['trial_id'],case['criterion_text'],rule],sort_keys=True)
        reader=extract(case['note'])
        if reader['scope']=='multiple_subjects':raise ValueError('Multiple-subject case in record cohort')
        selected={k:(f['value'],f['sentences']) for k,f in reader['facts'].items()
                  if k in rule['facts'] and supports(k,rule['facts'][k])}
    else:
        for k,spec in rule['facts'].items():
            spec['role']=roles.get(k,spec['role'])
        fingerprint=json.dumps(sorted((c['criterion_type'],c['criterion_text']) for c in rows if c['trial_id']==case['trial_id']))
        selected={k:v for k,v in known.get(case['patient_id'],{}).items() if k in rule['facts']}
    version=digest(fingerprint.encode())
    p=make_packet({cid:rule},{cid:{k:v[0] for k,v in selected.items()}},case['trial_id'],version,patient=case['patient_id'])
    source=dict(re.findall(r'^(\d+)\. (.*)$',case['note'],re.M))
    for e in p['bundle']['entry']:
        d=e['resource']
        if d['resourceType']=='DocumentReference':
            key=next(k for k in selected if d['id']=='src-'+contract(rule['facts'][k]))
            evidence='\n'.join(source[str(i)] for i in selected[key][1])
            d['content'][0]['attachment'].update(title=case['patient_id'], data=base64.b64encode(evidence.encode()).decode())
    return p,version

def run(db):
    audit=list(csv.DictReader((DATA/'round5/PocketMD_82_Case_Audit.csv').open()))
    ids={a['annotation_id'] for a in audit if a['suggested_route']=='retrieve_record'}
    expected=load(DATA/'round4/source_receipt.json')['source_sha256']
    topics={}
    for year,h in expected.items():
        raw=(HERE/(year+'.xml')).read_bytes()
        if digest(raw)!=h:raise ValueError('Unexpected public topic version')
        topics[year]=ET.fromstring(raw)
    cases=[]; indexed={}
    for folder in [DATA,DATA/'round2',DATA/'round3']:
        rows=load(folder/'blind.json'); rules=load(folder/'rules.json')
        known={} if folder.name=='round3' else load(folder/'facts.json')
        for c in rows:
            cid=str(c['annotation_id'])
            if cid not in ids:continue
            p,version=packet(folder,rows,c,rules[cid],known)
            pid=c['patient_id']; docs=texts(c,topics)
            if pid in indexed and indexed[pid]!=docs:raise ValueError('Inconsistent patient case')
            if pid not in indexed:
                for kind,parts in docs.items():
                    logical=pid+'/'+kind
                    add_document(db,'Patient/'+pid,logical,digest(json.dumps(parts).encode()),'2026-05-01T00:00:00Z',
                                 kind,parts,[logical])
                indexed[pid]=docs
            cases.append((cid,p,version,c,rules[cid]))
    if len(cases)!=len(ids) or len(ids)!=63:raise ValueError('Frozen cohort changed')
    report=[];groups=set()
    for cid,p,v,c,rule in cases:
        # Independently read the linked public sources for explicit values under the existing
        # vignette contracts. Never treat these texts as practitioner-authored flowsheets.
        observed={}
        for kind,parts in indexed[c['patient_id']].items():
            numbered='\n'.join(f'{n}. {line}' for n,line in parts)
            for key,fact in extract(numbered)['facts'].items():
                if key in rule['facts'] and supports(key,rule['facts'][key]):
                    observed.setdefault(key,[]).append((kind,fact['value'],fact['sentences']))
        out=retrieve(db,{cid:rule},p,c['trial_id'],v)
        fresh={k:hits for k,hits in observed.items() if out['after'][cid]['facts'].get(k,{}).get('state')!='AVAILABLE'}
        lookups=out['lookups']
        # Some audited record needs sit behind a protocol/role gate. Search their
        # criterion wording while retaining the engine's original disposition and owner.
        query=' '.join(q['needed'] for q in lookups) or c['criterion_text']
        patient='Patient/'+c['patient_id']; at=p['context']['as_of']
        ranked=search(db,patient,at,query,limit=5)
        numbered=search(db,patient,at,query,limit=5,kind='NIH vignette')
        plain=search(db,patient,at,query,limit=5,kind="NIH vignette",expand_aliases=False)
        groups.update(q['source_request_id'] for q in lookups)
        report.append(dict(annotation_id=int(cid),patient=c['patient_id'],trial=c['trial_id'],criterion=c['criterion_text'],
            before=out['before'][cid],after=out['after'][cid]['state'],active_record_requests=len(lookups),
            new_public_numeric_leads=json.dumps(fresh,sort_keys=True),search_terms=query,suggested_records=' | '.join(sorted({q['suggested_record'] for q in lookups})),
            lookup_mode='active record request' if lookups else 'audit fallback search',
            lead_sources=' | '.join(f"{x['source']} [{x['locator']}]" for x in ranked),
            top_source_excerpt=ranked[0]['passage'] if ranked else '',nih_top5=[int(x['locator']) for x in numbered],lexical_top5=[int(x['locator']) for x in plain],
            evidence_backed=bool(out['work']['evidence_backed_decisions'])))
    report.sort(key=lambda x:x['annotation_id'])
    frozen=digest(json.dumps(report,sort_keys=True).encode())
    citations={int(a['annotation_id']):ast.literal_eval(a['physician_sentence_ids'] or '[]') for a in audit}
    for row in report:
        cited=citations[row['annotation_id']]
        row.update(physician_sentence_ids=cited, citation_in_top5=bool(set(cited)&set(row['nih_top5'])) if cited else '')
    with (HERE/'PocketMD_63_Retrieval_Results.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=report[0]);writer.writeheader();writer.writerows(report)
    result=dict(criteria=len(report),patients=len(indexed),source_texts=sum(map(len,indexed.values())),
                rows_with_leads=sum(bool(r['lead_sources']) for r in report),rows_with_active_requests=sum(bool(r['active_record_requests']) for r in report),
                grouped_source_requests=len(groups),cited_rows=sum(bool(r['physician_sentence_ids']) for r in report),
                top5_overlap=sum(r['citation_in_top5'] is True for r in report),
                lexical_top5_overlap=sum(bool(set(r['physician_sentence_ids']) & set(r['lexical_top5'])) for r in report),
                new_definite=sum(r['before'] not in ('MET','NOT_MET') and r['evidence_backed'] for r in report),
                rows_with_new_numeric_leads=sum(r['new_public_numeric_leads']!='{}' for r in report),after=dict(Counter(r['after'] for r in report)),prediction_sha256=frozen,topic_sha256=expected)
    (HERE/'receipt.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
if __name__=='__main__':
    with closing(connect(':memory:')) as db:run(db)
