"""Bounded research fixtures. PK values are synthetic and never dosing guidance."""
import argparse
from base64 import b64encode
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
import normalized as n
import therapy_adapter as t

def concept(system,code):return {"coding":[{"system":system,"code":code}]}

def fixture(rules, *, days=10, half_days=2, ingredients=("21212",), empty=False):
    packet=n.make_packet(rules,{},stamp="2026-05-23T12:00:00Z")
    ctx=packet["context"]; b=packet["bundle"]
    ctx["therapy_receipts"]={}
    subject={"reference":"Patient/demo"}; enc={"reference":"Encounter/screen"}; stamp=ctx["as_of"]
    def make(kind,key,**attrs):
        return {"resourceType":kind,"id":key,"meta":{"versionId":"1","lastUpdated":stamp},**attrs}
    def add(resource):
        pointer=n.ref(resource)
        doc=make("DocumentReference","support-"+resource['id'],status="current",subject=subject,date=stamp,
                 author=[{"reference":"Organization/demo-record"}],identifier=[{"system":n.SOURCE,"value":n.HASH}],
                 content=[{"attachment":{"contentType":"application/json","title":"Synthetic medication documentation",
                             "data":b64encode(n.canonical(resource)).decode()}}])
        ctx["therapy_receipts"][pointer]={"source":n.ref(doc),"sha256":sha256(n.canonical([resource,doc])).hexdigest()}
        b["entry"].extend(({"resource":resource},{"resource":doc}))
        return resource
    anchor=add(make("MedicationAdministration","first",status="completed",subject=subject,context=enc,
                    identifier=[{"system":t.SESSION,"value":n.HASH+"|first-SOT106"}],
                    medicationCodeableConcept=concept(t.SUPPORT,"SOT106"),effectiveDateTime=stamp))
    r=None
    route=concept("urn:pocketmd:research:route","demo-oral")
    if not empty:
        med=add(make("Medication","drug",status="active",ingredient=[
            {"itemCodeableConcept":concept(t.RX,code),"isActive":True} for code in ingredients]))
        stop=(n.instant(stamp)-timedelta(days=days)).isoformat()
        r=add(make("MedicationAdministration","prior",status="completed",context=enc,subject=subject,effectiveDateTime=stop,
                   medicationReference={"reference":n.ref(med)},dosage={"route":route}))
        for code in ingredients:
            if half_days is None: continue
            add(make("Observation","pk-"+code,status="final",subject=subject,encounter=enc,effectiveDateTime=stamp,issued=stamp,
                     code=concept(t.SUPPORT,"elimination-half-life"),focus=[{"reference":n.ref(r)}],
                     valueQuantity={"system":n.UCUM,"code":"d","value":half_days},
                     component=[{"code":concept(t.SUPPORT,"ingredient"),"valueCodeableConcept":concept(t.RX,code)},
                                {"code":concept(t.SUPPORT,"route"),"valueCodeableConcept":route}]))
    reconciled=make("List","reconciliation",status="current",mode="snapshot",subject=subject,encounter=enc,
                    code=concept(t.SUPPORT,"complete-administered-drug-history"),date=stamp,
                    extension=[{"url":t.THROUGH,"valueInstant":stamp}],entry=[] if not r else [{"item":{"reference":n.ref(r)}}])
    if empty:reconciled["emptyReason"]=concept("http://terminology.hl7.org/CodeSystem/list-empty-reason","nilknown")
    add(reconciled)
    return packet

def find(p,id):return next(e["resource"] for e in p["bundle"]["entry"] if e["resource"]["id"]==id)

def trust(p,r):
    receipt=p['context']['therapy_receipts'][n.ref(r)]
    doc=next(e['resource'] for e in p['bundle']['entry'] if n.ref(e['resource'])==receipt['source'])
    receipt['sha256']=sha256(n.canonical([r,doc])).hexdigest()

def planned(p):
    r=find(p,'first')
    receipt=p['context']['therapy_receipts'].pop(n.ref(r))
    r['resourceType']='MedicationRequest'
    r['status']='active'
    r['intent']='order'
    r['identifier'][0]['value']=n.HASH+'|planned-first-SOT106'
    r['encounter']=r.pop('context')
    r['authoredOn']=r.pop('effectiveDateTime')
    r['dosageInstruction']=[{'timing':{'event':['2026-05-30T12:00:00Z']}}]
    p['context']['therapy_receipts'][n.ref(r)]=receipt
    trust(p,r)
    return p

def second_inhibitor(p, other):
    renamed={'drug':'drug2','prior':'prior2','pk-703':'pk-703-second'}
    source_rows=[deepcopy(find(other,old)) for old in renamed]
    replacement={n.ref(r):n.ref({**r,'id':renamed[r['id']]}) for r in source_rows}
    for r in source_rows:
        old=r['id']
        r['id']=renamed[old]
        if old=='prior':
            r['medicationReference']['reference']=replacement[r['medicationReference']['reference']]
        if old=='pk-703':
            r['focus'][0]['reference']=replacement[r['focus'][0]['reference']]
        doc=deepcopy(find(other,'support-'+old))
        doc['id']='support-'+r['id']
        doc['content'][0]['attachment']['data']=b64encode(n.canonical(r)).decode()
        p['bundle']['entry'].extend([{'resource':r},{'resource':doc}])
        p['context']['therapy_receipts'][n.ref(r)]={'source':n.ref(doc)}
        trust(p,r)
    rec=find(p,'reconciliation')
    rec['entry'].append({'item':{'reference':n.ref(find(p,'prior2'))}})
    trust(p,rec)
    return p

def checks(rules):
    def get(p):return t.derive(rules,p['bundle'],p['context'])
    specs=(rules.get('E05') or rules['106S01-E05'])['facts']
    key={name:n.contract(fact) for name,fact in specs.items()}
    results=[]
    def expect(name,p,want):
        got=get(p)
        actual={name:got[ptr][0] for name,ptr in key.items() if ptr in got}
        assert actual==want,(name,actual,want)
        assert all(entry[2] and all('/_history/' in r for r in entry[2]) for entry in got.values()),name
        results.append(name)
    exist={t.DRUG:True}
    all_values={**exist,t.DAYS:10.0,t.LIVES:5.0}
    expect("known inhibitor/ten days/five sourced half-lives",fixture(rules),all_values)
    expect("seven-day boundary",fixture(rules,days=7,half_days=1),{**exist,t.DAYS:7.0,t.LIVES:7.0})
    expect("six days despite six half-lives",fixture(rules,days=6,half_days=1),{**exist,t.DAYS:6.0,t.LIVES:6.0})
    expect("four half-lives despite eight days",fixture(rules,days=8,half_days=2),{**exist,t.DAYS:8.0,t.LIVES:4.0})
    p=second_inhibitor(fixture(rules),fixture(rules,days=15,half_days=4,ingredients=('703',)))
    expect("two inhibitors set independent minima",p,{**exist,t.DAYS:10.0,t.LIVES:3.75})
    expect("no medicine or source search is insufficient",{**fixture(rules),"context":{**fixture(rules)['context'],"therapy_receipts":{}}},{})
    expect("empty reconciled history",fixture(rules,empty=True),{t.DRUG:False})
    expect("unregistered drug cannot clear history",fixture(rules,ingredients=("unmapped",)),{})
    expect("partial multicomponent group cannot classify",fixture(rules,ingredients=("1484911",)),{})
    expect("complete three-agent combination",fixture(rules,ingredients=("1484911","1799206","1939323")),all_values)
    expect("half-life unknown",fixture(rules,half_days=None),{**exist,t.DAYS:10.0})
    p=fixture(rules);r=find(p,"pk-21212");r['component'][1]['valueCodeableConcept']=concept('urn:example:route','wrong-route');trust(p,r)
    expect("route-specific PK mismatch",p,{**exist,t.DAYS:10.0})
    p=fixture(rules);r=find(p,"pk-21212");r["valueQuantity"]['code']='mg';trust(p,r)
    expect("mass cannot stand in for a half-life",p,{**exist,t.DAYS:10.0})
    p=fixture(rules);r=find(p,"pk-21212");r["focus"]=[{'reference':'MedicationAdministration/missing/_history/1'}];trust(p,r)
    expect("PK amount must reference exact administered product",p,{**exist,t.DAYS:10.0})
    p=fixture(rules);r=find(p,"prior");r["medicationReference"]={'reference':'Medication/drug'};trust(p,r)
    expect("unversioned product refused",p,{})
    p=fixture(rules);r=find(p,"reconciliation");r['entry']=[];trust(p,r)
    expect("omitted present medicine cannot establish full history",p,exist)
    p=fixture(rules);r=find(p,"reconciliation");r['extension'][0]['valueInstant']='2026-05-22T12:00:00Z';trust(p,r)
    expect("history reconciled before first dose",p,exist)
    p=fixture(rules);r=find(p,"reconciliation");del p['context']['therapy_receipts'][n.ref(r)]
    expect("unsigned history gives positive only",p,exist)
    p=fixture(rules);find(p,"support-prior")['content'][0]['attachment']['title']='changed'
    expect("changed source fails pinned digest",p,{})
    p=fixture(rules);find(p,"support-prior")['content'][0]['attachment'].pop('data');trust(p,find(p,'prior'))
    expect("source title alone cannot verify exposure",p,{})
    p=fixture(rules,empty=True);p['bundle']['entry'].append({"resource":{"resourceType":"MedicationAdministration","id":"incomplete",
            "status":"completed","subject":{"reference":"Patient/demo"}}})
    expect("unversioned administration contradicts a complete empty history",p,{})
    p=fixture(rules);r=find(p,'prior');r['subject']={'reference':'Patient/other'};trust(p,r)
    expect("other patient administration withheld",p,{})
    p=fixture(rules,empty=True);r=find(p,'reconciliation');r.pop('emptyReason');trust(p,r)
    expect("empty list without affirmative no-known history",p,{})
    p=fixture(rules);r=find(p,'first');r['status']='not-done';trust(p,r)
    expect("omitted first dose cannot settle washout",p,{})
    p=fixture(rules);r=find(p,'first');r['medicationCodeableConcept']=concept(t.SUPPORT,'wrong-study-product');trust(p,r)
    expect("first-dose tag cannot substitute for the study drug",p,{})
    expect("planned next-week first dose supports historical exposure only",planned(fixture(rules)),exist)
    expect("empty as-of history cannot predict future planned-date exposure",planned(fixture(rules,empty=True)),{})
    p=planned(fixture(rules));r=find(p,'first');r['dosageInstruction'][0]['timing']['event']=['2026-05-22T12:00:00Z'];trust(p,r)
    expect("stale planned dose needs actual evidence",p,{})
    p=fixture(rules);r=find(p,'prior');r['effectivePeriod']={'start':r.pop('effectiveDateTime')};r['status']='in-progress';trust(p,r)
    expect("ongoing confirmed at anchor gives zero washout",p,{**exist,t.DAYS:0.0,t.LIVES:0.0})
    r['meta']['lastUpdated']='2026-05-22T12:00:00Z';trust(p,r)
    expect("old in-progress record may have subsequently ended",p,exist)
    p=fixture(rules);p['context']['enabled_contracts']=[]
    expect("caller-disabled mappings withheld",p,{})
    return results

def load_rules():
    root=Path(__file__).resolve().parent
    for f in (root/'rules.json',root/'sotio_rules.json',root.parent/'authoring/therapy/rules.json'):
        if f.exists():
            j=json.loads(f.read_text());j=j.get('rules',j)
            if 'E05' in j or '106S01-E05' in j:return j
    raise ValueError("Provide a SOTIO rules JSON file.")

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--rules',type=Path);parser.add_argument('--example',action='store_true')
    args=parser.parse_args();rules=json.loads(args.rules.read_text()) if args.rules else load_rules()
    print(json.dumps(fixture(rules) if args.example else checks(rules),indent=2))
