"""Build patient-scoped FHIR R4 transaction bundles and a local searchable resource store."""
import argparse
import base64
import csv
from collections import Counter,defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
import sys
HERE=Path(__file__).resolve().parent
R8=HERE.parent/'round8'
sys.path.insert(0,str(R8))
from run import abstract,admits
from clinical_fields import from_line, STUDY_TAG

BASE='https://pocketmd.example/fhir'
LOCAL='urn:pocketmd:trialgpt:clinical:v1'
SCOPE='urn:pocketmd:trialgpt:evidence-context'
LINE='urn:pocketmd:trialgpt:source-sentence'
UNIT='http://unitsofmeasure.org'
LOINC='http://loinc.org'
RX='http://www.nlm.nih.gov/research/umls/rxnorm'
ICD='http://hl7.org/fhir/sid/icd-10-cm'
# Numeric measures use standard coding only when the source supports the meaning.
MEASURES={
 'age-at-presentation':('30525-0','Age'), 'heart_rate':('8867-4','Heart rate'),
 'respiratory_rate':('9279-1','Respiratory rate'), 'body-temperature':('8310-5','Body temperature'),
 'serum_creatinine_mg_dl':('2160-0','Creatinine [Mass/volume] in Serum or Plasma'),
 'hemoglobin':('718-7','Hemoglobin [Mass/volume] in Blood'), 'gcs':('9269-2','Glasgow coma score total'),
 'blood-pressure':('85354-9','Blood pressure panel'), 'systolic':('8480-6','Systolic blood pressure'),
 'diastolic':('8462-4','Diastolic blood pressure')}
def hashtext(s):return sha256(s.encode()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
def dump(p,x):Path(p).write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n')
def rid(r):return r['resourceType']+'/'+r['id']
def ref(s):return {'reference':s}
def described(key):
    return key.replace('-',' ').replace('_',' ')
def concept(k,other=None):
    items=[{'system':LOCAL,'code':k.replace(' ','-'),'display':described(k)}]
    if other:
        system,code,display=other
        items.append({'system':system,'code':code,'display':display})
    return {'coding':items,'text':described(k)}
def q(val,unit):
    return {'value':val,**({'system':UNIT,'code':unit,'unit':unit} if unit else {})}
def review_table():
    out=defaultdict(list)
    for line in (HERE/'source_review.psv').read_text().splitlines():
        if line and not line.startswith('#'):
            case,n,typ,key,quote,scope,*qty=line.split('|')
            out['sigir-'+case].append((int(n),typ,key,quote,scope,qty))
    return out

INTRO=re.compile(r'^(?:(?:A|An) |Karen is a |A physician is called to see a )?(\d{1,3})(?:[- ]?(year|month)[- ]old|\s*(yo))\b',re.I)
BP=re.compile(r'\b(?:blood pressure|BP)\s*(?:is|was|of|:)?\s*(\d{2,3})\s*/\s*(\d{2,3})(?:\s*(mm\s*Hg))?',re.I)

def build_case(pid,note,curated,rx,icd,recorded):
    lines=dict((int(i),s) for i,s in re.findall(r'^(\d+)\. (.+)$',note,re.M))
    facts,group=abstract(note)
    subject=('Group/' if group else 'Patient/')+pid
    owner={'resourceType':subject.split('/')[0],'id':pid,'identifier':[{'system':'urn:nih:trialgpt:case','value':pid}]}
    if group:
        owner.update(type='person',actual=True)
        size=re.match(r'^A group of (\d+) ',lines[0],re.I)
        if size:owner['quantity']=int(size[1])
    doc='DocumentReference/'+pid+'-note'
    device={'resourceType':'Device','id':'pocketmd-r9','deviceName':[{'name':'PocketMD research converter R9','type':'user-friendly-name'}]}
    source=dict(resourceType='DocumentReference',id=doc.split('/')[1],status='current',subject=ref(subject),
                identifier=[{'system':'urn:pocketmd:sha256','value':hashtext(note)}],
                content=[{'attachment':{'contentType':'text/plain','data':base64.b64encode(note.encode()).decode(),
                                        'title':'TrialGPT numbered vignette '+pid}}])
    resources=[device,owner,source]; spanrows=[]
    def add(r,indices,scope,quote):
        if not indices or any(n not in lines for n in indices):raise ValueError('Invalid source sentence')
        if quote and not any(quote in lines[n] for n in indices):raise ValueError((pid,indices,quote))
        r.setdefault('extension',[]).append({'url':SCOPE,'valueString':scope})
        r['id']='n-'+hashtext(json.dumps([subject,r,indices,quote],sort_keys=True))[:30]
        prov=dict(resourceType='Provenance',id='p-'+r['id'][2:],target=[ref(rid(r))],recorded=recorded,
                  agent=[{'who':ref(rid(device))}],entity=[{'role':'source','what':ref(doc),
                  'extension':[{'url':LINE,'valueInteger':n} for n in indices]}])
        resources.extend([r,prov])
        spanrows.append(dict(subject=subject,resource=rid(r),document=doc,sentences=indices,context=scope,excerpt=quote))
    def observation(key,datum,ids,scope,quote):
        standard=(LOINC,*MEASURES[key]) if key in MEASURES else None
        r=dict(resourceType='Observation',status='final',subject=ref(subject),code=concept(key,standard),derivedFrom=[ref(doc)])
        add(r|datum,ids,scope,quote)
    if not group:
        age=INTRO.match(lines[0])
        if age:
            unit='mo' if (age[2] or '').lower()=='month' else 'a'
            observation('age-at-presentation',{'valueQuantity':q(int(age[1]),unit)},[0],'age at vignette presentation',age[0])
        for n,line in lines.items():
            statement=from_line(line)
            if statement:
                field,value,study=statement
                standard=(LOINC,field.standard,field.name) if field.standard else None
                r=dict(resourceType='Observation',status='final',subject=ref(subject),
                       code=concept(field.code,standard),derivedFrom=[ref(doc)])
                if study:r['extension']=[{'url':STUDY_TAG,'valueString':study}]
                if field.kind=='boolean':r['valueBoolean']=value
                elif field.kind=='quantity':r['valueQuantity']=q(value,field.unit)
                else:r['valueCodeableConcept']={'coding':[{'system':LOCAL+'/'+field.code,'code':value}]}
                add(r,[n],field.context,line)
            m=BP.search(line)
            if m and not re.search(r'\b(?:target|goal|if|mother|father|baseline was)\b',line,re.I):
                unit='mm[Hg]' if m[3] else None
                comp=[{'code':concept(k,(LOINC,*MEASURES[k])),'valueQuantity':q(int(m[i]),unit)}
                      for i,k in [(1,'systolic'),(2,'diastolic')]]
                observation('blood-pressure',{'component':comp},[n],'as documented; units supplied only if explicit',m[0])
            if line=="The patient will provide informed consent, and will comply with the trial protocol without any practical issues.":
                observation('stated-intention-to-consent',{'valueBoolean':True},[n],'prospective benchmark statement; written consent unverified',line)
        reviewed_keys={entry[2] for entry in curated}
        for k,(v,ids) in facts.items():
            if k in reviewed_keys or (k=='age_years' and age):continue
            if k=='age_years':
                observation('age-at-presentation',{'valueQuantity':q(v,'a')},ids,'age at vignette presentation',None)
            elif type(v) is bool:
                observation(k,{'valueBoolean':v},ids,'note abstraction',None)
            elif k in {'heart_rate','respiratory_rate','gcs','serum_creatinine_mg_dl'}:
                unit={'heart_rate':'/min','respiratory_rate':'/min','gcs':'1','serum_creatinine_mg_dl':'mg/dL'}[k]
                observation(k,{'valueQuantity':q(v,unit)},ids,'presentation',None)
        for n,ty,k,quote,scope,qty in curated:
            if ty=='Observation':
                if qty:
                    value,unit=qty
                    if not re.search(r'(?<![\d.])'+re.escape(value)+r'(?!\d)',quote):raise ValueError((k,quote,value))
                    datum={'valueQuantity':q(float(value) if '.' in value else int(value),unit)}
                else:datum={'valueString':quote}
                observation(k,datum,[n],scope,quote);continue
            r={'resourceType':ty}
            if ty=='MedicationStatement':
                entry=rx.get(k)
                std=(RX,entry['rxcui'],entry['name']) if entry else None
                r.update(subject=ref(subject),status='active' if scope=='active' else 'unknown',medicationCodeableConcept=concept(k,std),derivedFrom=[ref(doc)])
            elif ty=='Condition':
                entry=icd.get(k);std=(ICD,entry['code'],entry['display']) if entry else None
                r.update(subject=ref(subject),code=concept(k,std),evidence=[{'detail':[ref(doc)]}])
            elif ty=='Procedure':r.update(subject=ref(subject),status='completed',code=concept(k))
            elif ty=='FamilyMemberHistory':
                r.update(patient=ref(subject),status='partial',relationship={'text':scope},condition=[{'code':concept(k)}])
            else:raise ValueError(ty)
            add(r,[n],scope,quote)
    if len({rid(r) for r in resources})!=len(resources):raise ValueError('Duplicate resource identity')
    bundle={'resourceType':'Bundle','type':'transaction','id':pid+'-export','entry':[
      {'fullUrl':BASE+'/'+rid(r),'resource':r,'request':{'method':'PUT','url':rid(r)}} for r in resources]}
    return bundle,spanrows

def store(out,notes,recorded,builder=build_case):
    out.mkdir(parents=True,exist_ok=True)
    if any(out.iterdir()):raise ValueError('Use a new empty output directory')
    (out/'bundles').mkdir();(out/'ndjson').mkdir()
    reviewed=review_table();pins=load(HERE/'note_hashes.json')
    rx,icd=load(HERE/'rxnorm.json'),load(HERE/'icd10cm.json')
    resources={};spans=[];case_rows=[]
    with sqlite3.connect(out/'chart.sqlite') as db:
        db.executescript('CREATE TABLE resource(type TEXT,id TEXT,json TEXT,PRIMARY KEY(type,id)); CREATE TABLE membership(subject TEXT,type TEXT,id TEXT,PRIMARY KEY(subject,type,id)); CREATE TABLE coding(type TEXT,id TEXT,system TEXT,code TEXT); CREATE INDEX code_lookup ON coding(system,code,type,id);')
        for pid,note in sorted(notes.items()):
            if not re.fullmatch(r'sigir-\d+',pid):raise ValueError('Invalid identity')
            if pid in reviewed and hashtext(note)!=pins[pid]:raise ValueError('Source changed; recheck the reviewed assertions')
            b,ss=builder(pid,note,reviewed.get(pid,[]),rx,icd,recorded)
            dump(out/'bundles'/(pid+'.json'),b)
            subject=b['entry'][2]['resource']['subject']['reference'];spans.extend(ss)
            case_rows.append({'case':pid,'subject':subject,'sentences':len(note.splitlines()),'structured_facts':len(ss),'sentences_with_structured_facts':len({i for s in ss for i in s['sentences']})})
            for e in b['entry']:
                r=e['resource'];t,i=r['resourceType'],r['id']
                db.execute('INSERT INTO membership VALUES(?,?,?)',(subject,t,i))
                if rid(r) in resources:
                    if resources[rid(r)]!=r:raise ValueError('Conflicting duplicate')
                    continue
                resources[rid(r)]=r;db.execute('INSERT INTO resource VALUES(?,?,?)',(t,i,json.dumps(r)))
                for c in r.get('code',r.get('medicationCodeableConcept',{})).get('coding',[]):
                    db.execute('INSERT INTO coding VALUES(?,?,?,?)',(t,i,c['system'],c['code']))
    files=defaultdict(list)
    for r in resources.values():files[r['resourceType']].append(json.dumps(r,ensure_ascii=False))
    for t,rows in files.items():(out/'ndjson'/(t+'.ndjson')).write_text('\n'.join(rows)+'\n')
    lines_to_resources=defaultdict(list)
    for s in spans:
        for n in s['sentences']:lines_to_resources[(s['subject'].split('/')[1],n)].append(s['resource'])
    with (out/'sentence_coverage.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['case','sentence','source_text','has_structured_fact','resource_references'])
        for pid,note in sorted(notes.items()):
            for line in note.splitlines():
                index,body=line.split('. ',1);refs=lines_to_resources.get((pid,int(index)),[])
                w.writerow([pid,index,body,bool(refs),' | '.join(sorted(refs))])
    dump(out/'source_links.json',spans);dump(out/'cases.json',case_rows)
    receipt={'recorded':recorded,'cases':len(notes),'unique_resources':len(resources),'resource_counts':{t:len(r) for t,r in files.items()},
        'structured_facts':len(spans),'source_sentences':sum(r['sentences'] for r in case_rows),
        'sentences_with_structured_facts':sum(r['sentences_with_structured_facts'] for r in case_rows)}
    dump(out/'conversion.json',receipt);return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);p.add_argument('--notes',type=Path,default=HERE/'notes.json')
    p.add_argument('--recorded',default=None,help='Conversion timestamp; used only for Provenance.recorded.')
    a=p.parse_args();print(store(a.out,load(a.notes),a.recorded or datetime.now(timezone.utc).isoformat(timespec='seconds')))
