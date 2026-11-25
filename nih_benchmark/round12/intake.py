"""Create or enrich a patient FHIR chart from the original note, with exact source spans."""
import argparse
import base64
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
HERE=Path(__file__).resolve().parent
R9=HERE.parent/'round9'
sys.path.insert(0,str(R9))
from convert import BASE, LOCAL, LOINC, SCOPE, LINE, UNIT, concept, q, ref, rid, hashtext, store, build_case, load, dump
from clinical_fields import STUDY_TAG
from prose import walk
from narrative_evidence import GROUP
from benchmark_source import apply_benchmark_origin
from record_facts import UNITS,RX as DRUG_CODES,ICD as DX_CODES
from convert import MEASURES,RX,ICD

DEVICE='Device/pocketmd-prose-r12'
START='urn:pocketmd:source-char-start'
END='urn:pocketmd:source-char-end'
def device():
    return dict(resourceType='Device',id=DEVICE.split('/')[1],deviceName=[{'name':'PocketMD prose intake R12','type':'user-friendly-name'}])
def entry(r):
    return dict(fullUrl=BASE+'/'+rid(r),resource=r,request={'method':'PUT','url':rid(r)})

def enrich(bundle,spans,raw,stamp):
    items=[e['resource'] for e in bundle['entry']]
    doc=next(r for r in items if r['resourceType']=='DocumentReference')
    subject=doc['subject']['reference'];source=rid(doc)
    if subject.startswith('Group/'):return bundle,spans
    if base64.b64decode(doc['content'][0]['attachment']['data']).decode()!=raw:raise ValueError('Source mismatch')
    index={rid(r):r for r in items}
    seen=set()
    def identity(r,line):
        cc=r.get('code',r.get('medicationCodeableConcept',{}))
        code=next((c['code'] for c in cc.get('coding',[]) if c.get('system')==LOCAL),None)
        scope=tuple(sorted((v['url'],str(v.get('valueString',''))) for v in r.get('extension',[])))
        value={k:v for k,v in r.items() if k.startswith('value') or k=='component'}
        return (r['resourceType'],code, json.dumps(value,sort_keys=True),scope,line)
    for s in spans:
        for i in s['sentences']:
            seen.add(identity(index[s['resource']],i))
    for finding,coordinates in walk(raw):
        i,lo,hi=coordinates[0]
        indices=[pos[0] for pos in coordinates]
        f=finding.field
        key=f.code if f else finding.key
        scope=f.context if f else 'note abstraction'
        standard=(LOINC,f.standard,f.name) if f and f.standard else None
        obs=dict(resourceType='Observation',status='final',subject=ref(subject),code=concept(key,standard),derivedFrom=[ref(source)],
                 extension=[{'url':SCOPE,'valueString':scope}])
        if finding.study:obs['extension'].append({'url':STUDY_TAG,'valueString':finding.study})
        if key.startswith(('symptom:','prior-symptom:','recent-symptom:')):
            prefix,symptom=key.split(':',1)
            scope={'prior-symptom':'previous symptom history','recent-symptom':'reported recent history','symptom':'patient symptom report'}[prefix]
            obs['code']=concept('reported-'+symptom)
            obs['extension']=[{'url':SCOPE,'valueString':scope}]
            obs['valueBoolean']=finding.value
        elif key.startswith('medication:'):
            medication=key.split(':',1)[1]
            code=DRUG_CODES.get(medication)
            obs=dict(resourceType='MedicationStatement',status='active',subject=ref(subject),
                     medicationCodeableConcept=concept(medication,(RX,code['rxcui'],code['name']) if code else None),
                     derivedFrom=[ref(source)])
            scope='active'
            obs['extension']=[{'url':SCOPE,'valueString':scope}]
        elif key.startswith('condition:'):
            condition=key.split(':',1)[1];code=DX_CODES.get(condition)
            obs=dict(resourceType='Condition',subject=ref(subject),
                     code=concept(condition,(ICD,code['code'],code['display']) if code else None),
                     evidence=[{'detail':[ref(source)]}])
            scope=finding.value
            obs['extension']=[{'url':SCOPE,'valueString':scope}]
        elif key.startswith('quantity:'):
            measure=key.split(':',1)[1]
            obs['code']=concept(measure,(LOINC,*MEASURES[measure]))
            scope='age at vignette presentation' if measure=='age-at-presentation' else 'presentation'
            obs['extension']=[{'url':SCOPE,'valueString':scope}]
            obs['valueQuantity']=q(finding.value,finding.quantity_unit or UNITS[measure])
        elif not f or f.kind=='boolean':obs['valueBoolean']=finding.value
        elif f.kind=='quantity':obs['valueQuantity']=q(finding.value,f.unit)
        else:obs['valueCodeableConcept']={'coding':[{'system':LOCAL+'/'+key,'code':finding.value}]}
        existing_negation={'diabetes-mellitus':'denies-diabetes','trauma':'denies-trauma','fever':'fever-denied',
                           'upper-respiratory-symptoms':'upper-respiratory-symptoms-denied','headache':'headache-history-denied'}
        if key.startswith(('symptom:','recent-symptom:','prior-symptom:')) and finding.value is False:
            alias=existing_negation.get(key.split(':',1)[1])
            if alias and any(typ=='Observation' and code==alias and src==i for typ,code,_,_,src in seen):continue
        ident=identity(obs,i)
        if obs['resourceType']=='Condition':
            # A previously reviewed condition may carry more detailed scope.
            more_specific=any(s['sentences']==[i] and s['context'].split(';')[0]==scope
                              and index.get(s['resource'],{}).get('resourceType')=='Condition'
                              and index[s['resource']].get('code')==obs['code'] for s in spans)
            if more_specific:continue
        if ident in seen:continue
        seen.add(ident)
        uid=hashtext(json.dumps([subject,source,hashtext(raw),obs,coordinates],sort_keys=True))[:30]
        obs['id']='x-'+uid
        prov=dict(resourceType='Provenance',id='px-'+uid,target=[ref(rid(obs))],recorded=stamp,
                  agent=[{'who':ref(DEVICE)}],entity=[{'role':'source','what':ref(source),'extension':[
                      {'url':url,'valueInteger':offset} for pos in coordinates for url,offset in zip((LINE,START,END),pos)]}])
        if DEVICE not in index:
            index[DEVICE]=device();bundle['entry'].append(entry(index[DEVICE]))
        bundle['entry'].extend([entry(obs),entry(prov)])
        spans.append(dict(subject=subject,resource=rid(obs),document=source,sentences=indices,context=scope,
                          excerpt=' | '.join(raw[a:b] for _,a,b in coordinates),spans=coordinates,start=lo,end=hi,producer='prose-r12'))
    return bundle,spans

def plain_chart(patient,raw,stamp, *, document_id=None):
    if not re.fullmatch(r'[A-Za-z0-9.-]{1,45}',patient) or patient in {'.','..'}:raise ValueError('Invalid patient ID')
    if document_id is not None and (not re.fullmatch(r'[A-Za-z0-9.-]{1,64}',document_id) or document_id in {'.','..'}):
        raise ValueError('Invalid document ID')
    if not raw.strip():raise ValueError('Empty patient note')
    if GROUP.match(re.sub(r'^\s*(?:0\.\s+)?','',raw)) or re.match(r'^\s*(?:0\.\s+)?a cohort of',raw,re.I):
        raise ValueError('Supply an individual record to screen a patient')
    subj='Patient/'+patient
    doc=dict(resourceType='DocumentReference',id=document_id or patient+'-note',status='current',subject=ref(subj),
             identifier=[{'system':'urn:pocketmd:sha256','value':hashtext(raw)}],
             content=[{'attachment':{'contentType':'text/plain','data':base64.b64encode(raw.encode()).decode()}}])
    bundle=dict(resourceType='Bundle',type='transaction',id=patient+'-export',entry=[
        entry(dict(resourceType='Patient',id=patient)),entry(doc)])
    return enrich(bundle,[],raw,stamp)

def augmented_case(pid,raw,curated,rx,icd,recorded):
    b,spans=build_case(pid,raw,curated,rx,icd,recorded)
    return enrich(b,spans,raw,recorded)

def benchmark_chart(pid,raw,stamp):
    if GROUP.match(re.sub(r'^\s*(?:0\.\s+)?','',raw)):
        bundle,spans=build_case(pid,raw,[],{},{},stamp)
    else:
        bundle,spans=plain_chart(pid,raw,stamp)
    return apply_benchmark_origin(pid,raw,bundle,spans)


def benchmark_augmented_case(pid,raw,curated,rx,icd,recorded):
    bundle,spans=augmented_case(pid,raw,curated,rx,icd,recorded)
    return apply_benchmark_origin(pid,raw,bundle,spans)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('out',type=Path)
    p.add_argument('--notes',type=Path);p.add_argument('--recorded')
    p.add_argument('--frozen-trialgpt',action='store_true',help='Verify NIH dataset identity and mark its appended assumption.')
    p.add_argument('--note',type=Path);p.add_argument('--patient')
    a=p.parse_args();stamp=a.recorded or datetime.now(timezone.utc).isoformat(timespec='seconds')
    if a.note or a.patient:
        if not (a.note and a.patient) or a.notes:p.error('Supply --note and --patient together for single-patient mode')
        builder = benchmark_chart if a.frozen_trialgpt else plain_chart
        chart,_=builder(a.patient,a.note.read_bytes().decode(),stamp)
        dump(a.out,chart)
    else:
        source = a.notes or R9/'notes.json'
        is_frozen = a.frozen_trialgpt or source.resolve() == (R9/'notes.json').resolve()
        builder = benchmark_augmented_case if is_frozen else augmented_case
        print(store(a.out,load(source),stamp,builder=builder))
