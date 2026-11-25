"""SOTIO 106S01 Amendment 1 organ measurements on versioned FHIR R4 collection Bundles.

derive(rules, bundle, context) returns existing normalized contract IDs and value/issue/evidence/reason
tuples. Targets I14 (LVEF and method), I11 (PT/INR) and the laboratory portion of I10 (bilirubin,
ALT, AST). The adapter computes ULN ratios and calendar-day intervals from source quantities/dates.
The Gilbert/liver clinical contexts and investigator findings are supplied separately. It does not
select between discordant I11 interpretations.

Conventions in this research feed:
* A completed Procedure with LOCAL "main-icf-signed" records site confirmation of the main signature
  at performedDateTime, not merely the creation of a consent form. C1D1 comes from a completed
  MedicationAdministration of locally identified SOT106 bearing the study-specific C1D1 identifier,
  or a signed active ServiceRequest/order (LOCAL "c1d1-sot106") for a planned C1D1. The actual or
  planned status is preserved in the source references. A discordant prospective schedule requires
  reconciliation. The patient's screening Encounter is stamped for the specific study/hash.
* Dates are offset-qualified. Assessment and as-of timestamps are distinct. Site calendar boundaries
  use context.site_zone. Protocol labs must be collected and received during consented screening and
  on days 1–7 before C1D1. A site-received Communication for the exact report supplies receipt;
  Observation.issued alone cannot establish site receipt. Serum or plasma specimen codes, collection
  instant, final quantitative result and sole unqualified same-unit positive high reference bound are
  required. Each native FHIR observation uses its LOINC and UCUM code. The research-local modality
  codes ECHO/MUGA describe the actual imaging method. These exact codes require site crosswalks.
* Every source record used is dated, patient-linked, versioned and available as of the cutoff,
  with study/encounter scope. Each source document must be current, signed-source indexed under this
  protocol fingerprint and bear the mapped organization's identity. The caller supplies trusted-role
  enrollment and enabled contract IDs. These are synthetic trust/profile assumptions. Hospital
  identity, digital signature verification and product/site linkage must be established upstream.
"""
from collections import defaultdict
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

LOINC = 'http://loinc.org'
UCUM = 'http://unitsofmeasure.org'
MATERIAL = 'http://terminology.hl7.org/CodeSystem/v2-0487'
METHOD = 'urn:pocketmd:research:imaging-method'
LOCAL = 'urn:pocketmd:research:sotio-source-events:v1'
TARGETS = {
    'lvef': ('I14','10230-1',{'%'},None),
    'pt': ('I11','5902-2',{'s'},'PLAS'),
    'inr': ('I11','6301-6',{'1','{INR}'},'PLAS'),
    'tb': ('I10','1975-2',{'mg/dL','mg/L'},'SER'),
    'db': ('I10','1968-7',{'mg/dL','mg/L'},'SER'),
    'alt': ('I10','1742-6',{'U/L'},'SER'),
    'ast': ('I10','1920-8',{'U/L'},'SER'),
}
ERRORS = (ValueError, KeyError, TypeError, ArithmeticError, ZoneInfoNotFoundError, OverflowError, AttributeError)


def require(ok, detail):
    if not ok:
        raise ValueError(detail)


def code_values(cc, system):
    if not isinstance(cc,dict) or not isinstance(cc.get('coding'),list):
        return set()
    return {c.get('code') if isinstance(c.get('code'),str) and c['code'] else '<invalid>'
            for c in cc['coding'] if isinstance(c,dict) and c.get('system')==system}


def ref_value(obj, field):
    return (obj.get(field) or {}).get('reference')


def exact_link(snapshot, reference, kind):
    found=snapshot.exact.get(reference or '')
    require(found and found['resourceType']==kind and snapshot.current.get(kind+'/'+found['id'])==found,
            f'Provide the current, versioned {kind} source.')
    require(not found.get('modifierExtension') and not found.get('implicitRules'), f'Interpret {kind} modifiers first.')
    return found


def singleton(seq, why):
    require(len(seq)==1, why)
    return seq[0]


def doc_for(snapshot, source, allowed):
    from normalized import SOURCE,HASH,tag,ref,instant
    doc=exact_link(snapshot, source, 'DocumentReference')
    require(doc.get('status')=='current' and ref_value(doc,'subject')==snapshot.patient and tag(doc,SOURCE,HASH)
            and instant(doc['date'])<=instant(doc['meta']['lastUpdated'])<=snapshot.at
            and any(isinstance(item,dict) and isinstance(item.get('attachment'),dict)
                    and item['attachment'].get('contentType') and any(item['attachment'].get(k)
                        for k in ('title','data','url')) for item in doc.get('content',[])), 'Verify source document identity, date, and study scope.')
    who={a.get('reference') for a in doc.get('author',[])}
    require(who and who<=allowed, 'Unverified source document author.')
    return doc,ref(doc)


def event_sources(snapshot):
    from normalized import HASH,ref,tag,instant
    record=set(snapshot.registry.get('record',[]))
    site=set(snapshot.registry.get('site',[]))
    enc=snapshot.encounter
    scoped=[r for r in snapshot.current.values() if ref_value(r,'subject')==snapshot.patient]
    consent=[];actual=[];planned=[]
    for r in scoped:
        kind=r['resourceType']
        if r.get('status') in ('entered-in-error','revoked','cancelled','not-done','stopped'): continue
        if kind=='Procedure' and ref_value(r,'encounter')==enc and 'main-icf-signed' in code_values(r.get('code',{}),LOCAL):
            if r.get('status')!='completed': continue
            require(not r.get('modifierExtension') and not r.get('implicitRules'),'Unsupported consent event modifiers.')
            d,dref=doc_for(snapshot,singleton(r.get('report',[]),'Expected one documented signed-main-consent source.').get('reference'),site)
            who={ref_value(p,'actor') for p in r.get('performer',[])}
            require(who and who<=site,'Unknown consent verifier.')
            t=instant(r['performedDateTime'])
            require(t<=instant(d['date'])<=snapshot.at,'Consent event is not yet documented at cutoff.')
            consent.append((t, {ref(r),dref}))
        if kind=='MedicationAdministration' and ref_value(r,'context')==enc and tag(r,LOCAL,'C1D1|'+HASH):
            if r.get('status')!='completed':continue
            require(not r.get('modifierExtension') and not r.get('implicitRules') and code_values(r.get('medicationCodeableConcept',{}),LOCAL)=={'SOT106'},'Unverified C1D1 administration.')
            d,dref=doc_for(snapshot,singleton(r.get('supportingInformation',[]),'Expected a dosing source.').get('reference'),site|record)
            who={ref_value(p,'actor') for p in r.get('performer',[])}
            require(who and who<=set(snapshot.registry.get('investigator',[]))|record and all(x and x.split('/')[0] in ('Practitioner','PractitionerRole','Device') for x in who),'Unverified administrator.')
            t=instant(r['effectiveDateTime'])
            require(t<=instant(d['date'])<=snapshot.at,'First dose has not been documented at cutoff.')
            actual.append((t,{ref(r),dref}))
        if kind=='ServiceRequest' and ref_value(r,'encounter')==enc and 'c1d1-sot106' in code_values(r.get('code',{}),LOCAL):
            if r.get('status')!='active' or r.get('intent')!='order': continue
            require(not r.get('modifierExtension') and not r.get('implicitRules') and ref_value(r,'requester') in site,'Verify the study dosing order.')
            d,dref=doc_for(snapshot,singleton(r.get('supportingInfo',[]),'Expected the signed C1D1 schedule.').get('reference'),site)
            t=instant(r['occurrenceDateTime'])
            require(instant(r['authoredOn'])<=instant(d['date'])<=snapshot.at,'Dose schedule unavailable at cutoff.')
            require(instant(r['authoredOn'])<=t,'Retrospectively authored dosing plan cannot establish planned C1D1.')
            planned.append((t,{ref(r),dref}))
    sig,srefs=singleton(consent,'Supply one dated main-ICF signature event for this screening.')
    require(bool(actual or planned),'Supply actual or explicitly planned C1D1 with source evidence.')
    require(len(actual)<=1 and len(planned)<=1,'Reconcile multiple dosing events.')
    dose,drefs=(actual or planned)[0]
    require(not actual or not planned or actual[0][0]==planned[0][0],'Reconcile discrepant actual and planned C1D1.')
    if actual and planned:drefs=drefs|planned[0][1]
    require(dose>sig,'Reconcile the signed-consent and C1D1 sequence.')
    return sig,dose,srefs|drefs


def numeric(q, units):
    require(q.get('system')==UCUM and q.get('code') in units and 'comparator' not in q,
            'Verify exact result units and comparator.')
    v=q.get('value')
    require(type(v) in (int,float), 'A quantitative result is required.')
    d=Decimal(str(v))
    require(d.is_finite() and d>=0, 'Invalid numeric value.')
    return d


def read_measure(snap,key,r,anchors,zone):
    from normalized import ref,instant
    _,concept,units,material=TARGETS[key]
    allowed=set(snap.registry.get('record',[]))
    require(code_values(r.get('code',{}),LOINC)=={concept} and r.get('status') in ('final','amended','corrected')
            and not r.get('modifierExtension') and not r.get('implicitRules') and not r.get('dataAbsentReason'),
            'Provide a confirmed final, interpretable measurement.')
    require({k for k in r if k.startswith('value')}=={'valueQuantity'},'Provide a single quantitative value.')
    performers={a.get('reference') for a in r.get('performer',[])}
    require(performers and performers<=allowed, 'Unverified measurement performer.')
    d,dref=doc_for(snap,singleton(r.get('derivedFrom',[]),'Provide one versioned source report for this result.').get('reference'),allowed)
    require(performers & {x.get('reference') for x in d['author']},'Result and source lack a shared authorized performer.')
    eff=instant(r['effectiveDateTime']);issued=instant(r['issued'])
    require(eff<=issued<=instant(r['meta']['lastUpdated'])<=snap.at and eff<=instant(d['date'])<=snap.at, 'Measurement unavailable at this cutoff.')
    sig,dose,anc_refs=anchors
    refs=anc_refs|{ref(r),dref,ref(snap.current[snap.encounter]),ref(snap.current[snap.patient])}
    as_day=lambda dt:dt.astimezone(zone).date()
    require((as_day(dose)-as_day(sig)).days<=21,'Reconcile screening duration against the 21-day maximum.')
    def in_screen(t):
        return sig<t and 1<=(as_day(dose)-as_day(t)).days<=21
    raw=numeric(r['valueQuantity'],units)
    if material is None:
        require(raw<=100,'Invalid LVEF percent.')
        methods=code_values(r.get('method',{}),METHOD)
        require(len(methods)==1 and methods<={'ECHO','MUGA'},'Obtain evidence of an echo or MUGA.')
        return {'lvef':float(raw),'modality':next(iter(methods)), 'lvef_screen':in_screen(eff)},refs
    specimen=exact_link(snap,ref_value(r,'specimen'),'Specimen')
    require(specimen.get('status')=='available' and ref_value(specimen,'subject')==snap.patient and
            code_values(specimen.get('type',{}),MATERIAL)=={material}, 'Verify patient and specimen material.')
    require(instant(specimen['collection']['collectedDateTime'])==eff,'Reconcile collection and result effective times.')
    refs.add(ref(specimen))
    rr=singleton(r.get('referenceRange',[]),'An unambiguous reporting-lab reference interval is required.')
    require(not set(rr)-{'low','high'},'Resolve age-, text-, or context-specific reference interval before comparison.')
    hi=numeric(rr['high'],{r['valueQuantity']['code']})
    require(hi>0,'Upper reference limit must be positive.')
    if 'low' in rr: require(numeric(rr['low'],{r['valueQuantity']['code']})<=hi,'Inconsistent lab reference range.')
    receipt=[]
    for c in snap.current.values():
        if (c.get('resourceType')=='Communication' and ref_value(c,'subject')==snap.patient and ref_value(c,'encounter')==snap.encounter
            and any((p.get('contentReference') or {}).get('reference')==dref for p in c.get('payload',[]))
            and any('study-lab-result-receipt' in code_values(cat,LOCAL) for cat in c.get('category',[]))):
            require(c.get('status')=='completed' and not c.get('modifierExtension') and not c.get('implicitRules')
                    and ref_value(c,'sender') in allowed and any(rec.get('reference') in snap.registry.get('site',[]) for rec in c.get('recipient',[])),
                    'Verify the sender and study recipient of the final result.')
            received=instant(c['received'])
            require(issued<=received<=snap.at and instant(d['date'])<=received,'Result receipt is out of order or future at cutoff.')
            receipt.append((received,ref(c)))
    received,cref=singleton(receipt,'Provide a unique, dated site receipt for this exact final lab report.')
    refs.add(cref)
    col_days=(as_day(dose)-as_day(eff)).days; result_days=(as_day(dose)-as_day(received)).days
    return {key:float(raw/hi),key+'_col_days':col_days,key+'_result_days':result_days,
            key+'_screen':in_screen(eff) and in_screen(received)},refs


def derive(rules,bundle,context):
    from normalized import Snapshot,contract,ref
    grouped=defaultdict(list)
    snap=Snapshot(bundle,context)
    targets={code:key for key,(cid,code,_,_) in TARGETS.items() if cid in rules or '106S01-'+cid in rules}
    for r in snap.current.values():
        if r.get('resourceType')!='Observation' or ref_value(r,'subject')!=snap.patient or ref_value(r,'encounter')!=snap.encounter:
            continue
        for code in code_values(r.get('code',{}),LOINC)&targets.keys():
            grouped[targets[code]].append(r)
    derived={}
    if not grouped:return derived
    try:
        anchors=event_sources(snap)
        zone=ZoneInfo(context['site_zone'])
        anchor_error=None
    except ERRORS as exc:
        anchors=zone=None
        anchor_error=str(exc)
    for key,records in grouped.items():
        cid=TARGETS[key][0];spec=(rules.get(cid) or rules['106S01-'+cid])['facts']
        keys=[key,'modality','lvef_screen'] if key=='lvef' else [key,key+'_col_days',key+'_result_days',key+'_screen']
        refs={ref(r) for r in records}
        try:
            require(not anchor_error,anchor_error or 'Missing anchor.')
            o=singleton(records,'Reconcile multiple candidate measurements for this screening and analyte.')
            values,refs=read_measure(snap,key,o,anchors,zone)
            result=(None,'Bound from source-linked FHIR measurement.')
        except ERRORS as exc:
            values={k:None for k in keys}
            result=('MISSING_DATA',str(exc))
        for k in keys:
            h=contract(spec[k])
            if h in snap.enabled:
                derived[h]=(values[k],result[0],sorted(refs),result[1])
            else:
                derived[h]=(None,'BINDING_HOLD',[],'The source mapping is disabled for this technical profile.')
    return derived


def example(rules,criterion='I14'):
    """Build a synthetic native measurement packet for the selected criterion; no normalized fact rows."""
    from normalized import make_packet,ref,SOURCE,HASH
    criterion=criterion.removeprefix('106S01-')
    packet=make_packet(rules,{},stamp='2026-05-13T18:00:00Z')
    ctx,bundle=packet['context'],packet['bundle']; entries=bundle['entry']
    pat='Patient/demo';enc='Encounter/screen';org='Organization/demo-record';site='Organization/demo-site'
    data=lambda value:{'reference':value}
    def put(kind,i,**props):
        resource={'resourceType':kind,'id':i,'meta':{'versionId':'1','lastUpdated':ctx['as_of']},**props}
        entries.append({'resource':resource});return resource
    def doc(i,date,actor):
        return put('DocumentReference','report-'+i,status='current',subject=data(pat),author=[data(actor)],date=date,
                   identifier=[{'system':SOURCE,'value':HASH}],content=[{'attachment':{'contentType':'text/plain','title':'Synthetic '+i}}])
    def cc(sys,c):return {'coding':[{'system':sys,'code':c}]}
    def q(n,u):return {'value':n,'system':UCUM,'code':u}
    sig='2026-05-01T09:00:00Z';dose='2026-05-12T09:00:00Z'
    next(e['resource'] for e in entries if e['resource']['resourceType']=='Encounter')['period']['start']=sig
    d=doc('signed',sig,site)
    put('Procedure','consent-event',status='completed',code=cc(LOCAL,'main-icf-signed'),subject=data(pat),
        encounter=data(enc),performedDateTime=sig,performer=[{'actor':data(site)}],report=[data(ref(d))])
    d=doc('first-dose',dose,site)
    put('MedicationAdministration','first-dose',status='completed',identifier=[{'system':LOCAL,'value':'C1D1|'+HASH}],
        medicationCodeableConcept=cc(LOCAL,'SOT106'),subject=data(pat),context=data(enc),effectiveDateTime=dose,
        performer=[{'actor':data('PractitionerRole/demo-investigator')}],supportingInformation=[data(ref(d))])
    for key,(cid,lcode,units,material) in TARGETS.items():
        if cid!=criterion:continue
        eff='2026-05-06T10:00:00Z';issued='2026-05-07T16:00:00Z';d=doc(key,issued,org)
        fields=dict(status='final',code=cc(LOINC,lcode),subject=data(pat),encounter=data(enc),effectiveDateTime=eff,
                    issued=issued,performer=[data(org)],derivedFrom=[data(ref(d))])
        if key=='lvef':
            fields.update(valueQuantity=q(50,'%'),method=cc(METHOD,'ECHO'))
        else:
            sp=put('Specimen',key+'-spec',status='available',type=cc(MATERIAL,material),subject=data(pat),collection={'collectedDateTime':eff})
            value,high,unit={'pt':(18,12,'s'),'inr':(1.5,1,'1'),'tb':(1.5,1,'mg/dL'),'db':(.3,.3,'mg/dL'),
                             'alt':(70,28,'U/L'),'ast':(90,36,'U/L')}[key]
            fields.update(valueQuantity=q(value,unit),referenceRange=[{'high':q(high,unit)}],specimen=data(ref(sp)))
            put('Communication','receipt-'+key,status='completed',subject=data(pat),encounter=data(enc),
                category=[cc(LOCAL,'study-lab-result-receipt')],sender=data(org),recipient=[data(site)],
                received='2026-05-07T18:00:00Z',payload=[{'contentReference':data(ref(d))}])
        put('Observation',key,**fields)
    return packet
