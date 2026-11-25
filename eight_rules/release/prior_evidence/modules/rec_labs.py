"""REC-1245-101 protocol v5.0 §6.1 IC08 normalized FHIR R4 lab leaf research runner.

No patient data, pre-assigned outcomes, generic diagnosis inference, or site code crosswalk is
embedded. Evaluate(leaf, collection, anchors) requires an already authenticated synthetic or
validated site extract. 'verified' means the caller has authenticated the evidence source;
this demonstration does not implement EHR identity or cryptographic verification.

The 20 precise predicates are from the uploaded IC08 audit. 16 numeric laboratory leaves are
implemented. The diagnostic applicability flags are individually documented, version-linked
patient assessments supplied by the caller. Renal function is read from a method-specific
reported result; the module does not compute a clearance or infer formula inputs from sex.
No complete criterion or patient eligibility decision is emitted.
"""
import argparse
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal
import json
import operator
import re

STUDY = 'REC-1245-101'
VERSION = '5.0'
RULES = []
LOINC = 'http://loinc.org'
UCUM = 'http://unitsofmeasure.org'
MATERIAL = 'http://terminology.hl7.org/CodeSystem/v2-0487'
LOCAL = 'urn:pocketmd:synthetic:rec-lab-context'
REF = re.compile(r'^[A-Za-z]+/[A-Za-z0-9.-]{1,64}/_history/[A-Za-z0-9.-]{1,64}$')
UNITS = {
 'mass': {'g/dL':'1', 'g/L':'0.1'}, 'count': {'/uL':'1','10*3/uL':'1000','10*9/L':'1000'},
 'ratio': {'1':'1','{INR}':'1'}, 'enzyme': {'U/L':'1'}, 'bili': {'mg/dL':'1','mg/L':'0.1'},
 'clearance': {'mL/min':'1'}, 'indexed_gfr': {'mL/min/{1.73_m2}':'1'}
}
# Protocol Table 11 places albumin, transaminases and total bilirubin in serum chemistry;
# the bilirubin fractionation footnote refers to the current serum chemistry sample.
MEASURES = {
 'albumin': ('1751-7','SER','mass'), 'platelets': ('777-3','BLD','count'),
 'hemoglobin': ('718-7','BLD','mass'), 'inr': ('6301-6','PLAS','ratio'),
 'anc': ('751-8','BLD','count'), 'ast': ('1920-8','SER','enzyme'),
 'alt': ('1742-6','SER','enzyme'), 'total_bili': ('1975-2','SER','bili'),
 'direct_bili': ('1968-7','SER','bili'), 'adult_crcl': ('35591-7',None,'clearance'),
 'child_gfr': ('50384-7',None,'indexed_gfr')
}
# measure, comparator, cutoff, relative to result-specific ULN, prerequisite
TESTS = {
 'P001':('albumin','ge','2.8',False,None), 'P002':('platelets','ge','100000',False,None),
 'P003':('hemoglobin','ge','9',False,None), 'P004':('inr','le','1.7',False,None),
 'P005':('anc','ge','1500',False,None), 'P007':('ast','le','5',True,'hcc_or_liver_met'),
 'P008':('alt','le','5',True,'hcc_or_liver_met'), 'P009':('ast','le','3',True,'ordinary_liver'),
 'P010':('alt','le','3',True,'ordinary_liver'), 'P011':('total_bili','le','1.5',True,None),
 'P013':('total_bili','le','2',True,'hcc'), 'P015':('total_bili','le','3',True,'gilbert'),
 'P016':('total_bili','gt','1.5',True,None), 'P017':('direct_bili','le','1.5',True,'raised_total'),
 'P019':('adult_crcl','ge','60',False,'adult'), 'P020':('child_gfr','ge','60',False,'adolescent')
}
LEAVES = list(TESTS)
SOURCES = {m: 'https://loinc.org/'+v[0]+'/' for m,v in MEASURES.items()}
SOURCES['bedside_method'] = 'https://loinc.org/LL1929-0/'
LOCATOR = 'REC-1245-101 v5.0 PDF 47–48 §6.1 #8, PDF 53 §7.1.1 and PDF 74–75 §10.6.5/Table 11'
class Hold(ValueError): pass

def require(ok, message):
    if not ok: raise Hold(message)

def instant(text):
    require(isinstance(text,str) and 'T' in text, 'Timestamp lacks instant precision.')
    t=datetime.fromisoformat(text.replace('Z','+00:00'))
    require(t.utcoffset() is not None,'Timestamp needs a UTC offset.')
    return t

def ref(r):
    key=f"{r['resourceType']}/{r['id']}/_history/{r['meta']['versionId']}"
    require(REF.fullmatch(key),'Resource requires versioned identity.')
    return key

def coding(cc, system):
    return {x.get('code') for x in cc.get('coding',[]) if x.get('system')==system}

def amount(q,kind):
    require(q.get('system')==UCUM and q.get('code') in UNITS[kind] and 'comparator' not in q,
            'An exact numeric result in a verified UCUM unit is required.')
    require(type(q.get('value')) in (float,int,Decimal),'Invalid quantitative value.')
    v=Decimal(str(q['value']))*Decimal(UNITS[kind][q['code']])
    require(v.is_finite() and v>=0,'Invalid quantitative value.')
    return v

def upper(obs,kind):
    ranges=obs.get('referenceRange',[])
    require(len(ranges)==1,'Need one applicable local laboratory reference interval.')
    interval=ranges[0]
    require(not ({'age','appliesTo','type','text','extension'} & set(interval)),
            'The age-/sex-/method-dependent or textual reference interval has not been independently resolved.')
    ul=amount(interval['high'],kind)
    require(ul>0,'ULN must be positive.')
    return ul

def resource_index(bundle):
    require(bundle.get('resourceType')=='Bundle' and bundle.get('type')=='collection','Supply a normalized collection.')
    recs={}; logical=set()
    for entry in bundle.get('entry',[]):
        r=entry['resource']; k=ref(r); base=k.split('/_history/')[0]
        require(base not in logical,'Supply one as-of version for each logical resource.')
        require(not (r.get('implicitRules') or r.get('modifierExtension')),'Unresolved resource modifiers.')
        recs[k]=r;logical.add(base)
    return recs

def read_context(recs,a):
    require(a.get('study')==STUDY and a.get('version')==VERSION and a.get('verified') is True,
            'Require an authenticated, study/version-scoped normalized screening anchor packet.')
    patient=recs[a['patient']]; key=ref(patient).split('/_history/')[0]
    require(patient['resourceType']=='Patient','Incorrect patient resource.')
    enc=recs[a['encounter']]
    require(enc['resourceType']=='Encounter' and enc['subject']['reference']==key and
            enc['status'] in {'in-progress','finished'} and
            {(i.get('system'),i.get('value')) for i in enc.get('identifier',[])} >= {(LOCAL,STUDY+'|'+VERSION+'|screening')},
            'Wrong screening encounter, phase, or patient.')
    require(recs[a['local_lab']]['resourceType']=='Organization','Missing verified local laboratory identity.')
    # Study anchor document is the attested container; supplied instants must equal signed projection.
    doc=recs[a['context_ref']]
    end=instant(a['as_of']); anchors=a['events']
    require(doc['resourceType']=='DocumentReference' and doc['status']=='current' and doc['docStatus']=='final'
            and doc['subject']['reference']==key and doc.get('author')
            and instant(doc['date'])<=end, 'Invalid versioned screening anchor document.')
    agreement = {x.get('system'):x.get('value') for x in doc.get('identifier',[])}
    require(agreement.get(LOCAL+':site_zone')==a.get('site_zone') and bool(a.get('site_zone')),
            'Confirm the study site time zone for screening day boundaries.')
    zone=ZoneInfo(a['site_zone'])
    for k in ['consent','dose_day1','screening_start']:
        require(agreement.get(LOCAL+':'+k)==anchors[k], 'Anchor differs from verified source projection.')
    require(agreement.get(LOCAL)==STUDY+'|'+VERSION,'Anchor document is scoped to a different study.')
    require(all(instant(recs[k]['meta']['lastUpdated'])<=end for k in
                [a['encounter'],a['context_ref'],a['patient'],a['local_lab']]),'Anchor unavailable as of screening.')
    consent, day1, screening_start=(instant(anchors[k]) for k in ['consent','dose_day1','screening_start'])
    require(consent<=end<=day1 and screening_start<=end and instant(enc['period']['start'])==screening_start,
            'Invalid anchor ordering; screening must precede dosing.')
    finish=min(end,instant(enc['period']['end'])) if 'end' in enc['period'] else end
    require(screening_start<=finish,'Invalid encounter interval.')
    # Tables 1 and 3 label the screening days relative to the local Day 1 of dosing.
    earliest_screen_day=day1.astimezone(zone).date()-timedelta(days=28)
    earliest_instant=datetime.combine(earliest_screen_day,time.min,tzinfo=zone)
    return key, max(earliest_instant,consent,screening_start),finish,day1

def measurements(measure,recs,a,window):
    loinc,material,kind=MEASURES[measure]
    patient,begin,stop,day1=window
    lab=a['local_lab'].split('/_history/')[0]
    found=[]
    for key,obs in recs.items():
        if obs['resourceType']!='Observation' or obs.get('subject',{}).get('reference')!=patient: continue
        if obs.get('encounter',{}).get('reference')!=a['encounter'].split('/_history/')[0]:continue
        analytes=coding(obs.get('code',{}),LOINC)
        if loinc not in analytes: continue
        if obs.get('status') in {'entered-in-error','cancelled'}:continue
        measured=instant(obs['effectiveDateTime'])
        if measured<begin or measured>stop or measured>=day1: continue
        require(analytes=={loinc},'Ambiguous analyte coding.')
        require({k for k in obs if k.startswith('effective')}=={'effectiveDateTime'} and
                {k for k in obs if k.startswith('value')}=={'valueQuantity'} and
                not obs.get('component') and not obs.get('dataAbsentReason'),'Need a single unambiguous individual result.')
        require(obs.get('status') in {'final','amended','corrected'} and
                measured<=instant(obs['issued'])<=instant(a['as_of']) and
                instant(obs['meta']['lastUpdated'])<=instant(a['as_of']), 'Result unavailable or not final at screening.')
        drs=[(drk,dr) for drk,dr in recs.items() if dr['resourceType']=='DiagnosticReport' and
             any(x.get('reference')==key for x in dr.get('result',[])) and dr.get('subject',{}).get('reference')==patient and
             dr.get('status') in {'final','amended','corrected','appended'} and
             dr.get('encounter',{}).get('reference')==a['encounter'].split('/_history/')[0] and
             any(p.get('reference')==lab for p in dr.get('performer',[])) and
             instant(obs['issued'])<=instant(dr['issued'])<=instant(a['as_of']) and instant(dr['meta']['lastUpdated'])<=instant(a['as_of'])]
        require(len(drs)==1,'No single timely versioned final report from the verified local lab linked this exact result.')
        refs={key,drs[0][0],a['local_lab']}
        specimen_ref=obs.get('specimen',{}).get('reference')
        if material or specimen_ref:
            sp=recs.get(specimen_ref,{})
            acceptable={material} if material else {'SER','PLAS','BLD'}
            require(sp.get('resourceType')=='Specimen' and sp.get('subject',{}).get('reference')==patient and
                sp.get('status') in (None,'available') and len(coding(sp.get('type',{}),MATERIAL))==1
                and coding(sp.get('type',{}),MATERIAL)<=acceptable and instant(sp['meta']['lastUpdated'])<=instant(a['as_of']),
                'Missing, mismatched or unsuitable specimen for this assay.')
            refs.add(specimen_ref)
        if measure=='child_gfr':
            method=obs.get('method',{})
            require({(c.get('system'),c.get('code')) for c in method.get('coding',[])}=={(LOINC,'LA18032-5')}
                    and not(set(method) - {'coding'}),
                    'A general Schwartz result does not prove use of the bedside IDMS-traceable Schwartz equation.')
        if measure=='adult_crcl':
            # The specific LOINC code already asserts the method; reject an extra unverified method.
            require(not obs.get('method'),'Reconcile the additional adult clearance method with Cockcroft–Gault.')
        found.append((obs,amount(obs['valueQuantity'],kind),refs,specimen_ref))
    require(found,'No admissible measurement at screening.')
    return found

def dx_context(key,recs,a,window):
    # Qualified site fact entered by a reviewer using chart evidence; do not infer absence from absent Condition.
    patient,_,end,_=window; o=recs.get(a.get('conditions',{}).get(key),{})
    require(o.get('resourceType')=='Observation' and o.get('status') in {'final','amended','corrected'}
            and coding(o.get('code',{}),LOCAL)=={key} and o.get('subject',{}).get('reference')==patient
            and o.get('encounter',{}).get('reference')==a['encounter'].split('/_history/')[0]
            and o.get('performer') and {k for k in o if k.startswith('value')}=={'valueBoolean'}
            and type(o['valueBoolean']) is bool and not o.get('dataAbsentReason')
            and window[1]<=instant(o['effectiveDateTime'])<=end and instant(o['effectiveDateTime'])<=instant(o['issued'])<=instant(a['as_of'])
            and instant(o['meta']['lastUpdated'])<=instant(a['as_of']), 'Require source-linked, verified patient-specific branch fact: '+key)
    links=o.get('derivedFrom',[]); require(len(links)==1,'Need diagnosis context source.')
    doc=recs.get(links[0].get('reference'),{})
    require(doc.get('resourceType')=='DocumentReference' and doc['subject']['reference']==patient and doc['status']=='current'
            and doc['docStatus']=='final' and any(x.get('reference') in {p.get('reference') for p in o['performer']} for x in doc.get('author',[]))
            and instant(doc['date'])<=instant(a['as_of']) and instant(doc['meta']['lastUpdated'])<=instant(a['as_of']), 'Invalid diagnosis context source.')
    return o['valueBoolean'],{ref(o),ref(doc)}

def applicability(branch,recs,a,window):
    if branch in (None,'raised_total'):return True,set()
    if branch in {'adult','adolescent'}:
        p=recs[a['patient']]; born=date.fromisoformat(p['birthDate'])
        ages=[]
        # Do not guess a cutoff when a birthday crosses an age stratum during screening.
        for when in (window[1],window[2],window[3]):
            d=when.astimezone(ZoneInfo(a['site_zone'])).date()
            if born.month==2 and born.day==29 and d.month==2 and d.day==28:
                require(False,'Confirm leap-day age convention at governance boundary.')
            ages.append(d.year-born.year-((d.month,d.day)<(born.month,born.day)))
        categories=['adult' if x>=18 else 'adolescent' if x>=12 else 'child' for x in ages]
        require(len(set(categories))==1,'Confirm the age stratum when a birthday crosses protocol groups during screening.')
        return categories[0]==branch,{a['patient']}
    if branch in {'hcc','gilbert'}:return dx_context(branch,recs,a,window)
    flags=[]; evidence=set()
    for k in ['hcc','liver_met']:
        try:
            flag,refs=dx_context(k,recs,a,window)
        except (Hold,KeyError,TypeError,ValueError):
            flag=None;refs=set()
        flags.append(flag);evidence|=refs
    require(True in flags or None not in flags,'Need HCC or liver metastasis status to choose the branch.')
    has_liver=True in flags
    return (not has_liver if branch=='ordinary_liver' else has_liver),evidence

def evaluate(leaf,bundle,anchors):
    leaf=leaf.split('/')[-1]; refs=set()
    if leaf not in TESTS:raise ValueError('Unsupported IC08 lab leaf: '+leaf)
    name,op,threshold,ratio,branch=TESTS[leaf]
    try:
        recs=resource_index(bundle); window=read_context(recs,anchors)
        refs.update(anchors[k] for k in ['patient','encounter','context_ref'])
        applies,support=applicability(branch,recs,anchors,window);refs|=support
        if not applies:return receipt(leaf,'NOT_APPLICABLE','Documented patient branch does not apply.',refs)
        fractions=None
        if branch=='raised_total':
            total = measurements('total_bili',recs,anchors,window)
            elevated=set(); flags=set()
            for o,v,r,sp in total:
                flags.add(v > Decimal('1.5')*upper(o,'bili'));elevated.add(sp);refs|=r
            require(len(flags)==1,'Resolve discordant screening total bilirubin results before reflex testing.')
            if flags=={False}:return receipt(leaf,'NOT_APPLICABLE','Total bilirubin did not trigger direct bilirubin.',refs)
            fractions=elevated
        readings=measurements(name,recs,anchors,window); outcomes=set()
        sampled=set()
        for o,v,r,sp in readings:
            if fractions is not None and sp not in fractions:continue
            refs|=r; sampled.add(sp)
            limit=Decimal(threshold)*(upper(o,MEASURES[name][2]) if ratio else 1)
            outcomes.add({'ge':operator.ge,'le':operator.le,'gt':operator.gt}[op](v,limit))
        require(outcomes and (fractions is None or fractions<=sampled),'Need direct bilirubin from each qualifying elevated total bilirubin sample.')
        require(len(outcomes)==1,'Discordant eligible results straddle the threshold; no selection priority is assumed.')
        decision='MET' if outcomes.pop() else 'NOT_MET'
        return receipt(leaf,decision,'Protocol laboratory predicate evaluated.',refs)
    except (KeyError,TypeError,AttributeError,ValueError,ArithmeticError) as e:
        return receipt(leaf,'MISSING_DATA','Cannot establish this laboratory predicate: '+str(e),refs)

def receipt(leaf,state,reason,refs):
    return {'study':STUDY,'version':VERSION,'criterion':'I08','predicate':leaf,'state':state,'reason':reason,
            'evidence':sorted(refs),'source':LOCATOR,'measure':MEASURES[TESTS[leaf][0]][0],'scope':'leaf only'}

def synthetic(leaf,pass_test=True):
    """Return a dated, fictional normalized FHIR collection and authenticated-fixture context."""
    name,op,target,relative,branch=TESTS[leaf]
    clock='2026-06-15T12:00:00Z'; measured='2026-06-13T09:00:00Z'
    encounter='Encounter/v'; subject={'reference':'Patient/p'}; visit={'reference':encounter}
    resources=[]
    def add(kind,id,stamp=measured,**fields):
        r={'resourceType':kind,'id':id.replace('_','-'),'meta':{'versionId':'1','lastUpdated':stamp},**fields}
        resources.append(r);return ref(r)
    def cc(system,code):return {'coding':[{'system':system,'code':code}]}
    def quantity(value,unit):return {'value':value,'system':UCUM,'code':unit}
    anchors={'study':STUDY,'version':VERSION,'verified':True,'as_of':clock,'site_zone':'America/Los_Angeles',
             'events':{'consent':'2026-06-01T10:00:00Z','dose_day1':'2026-06-16T10:00:00Z','screening_start':'2026-06-01T11:00:00Z'},'conditions':{}}
    hcc=branch in ('hcc','hcc_or_liver_met')
    anchors['patient']=add('Patient','p',birthDate='2011-03-03' if branch=='adolescent' else '1980-03-03')
    anchors['encounter']=add('Encounter','v',subject=subject,status='in-progress',period={'start':anchors['events']['screening_start']},
                             identifier=[{'system':LOCAL,'value':STUDY+'|'+VERSION+'|screening'}])
    anchors['local_lab']=add('Organization','site-lab',name='Synthetic local laboratory')
    anchors['context_ref']=add('DocumentReference','screen-anchors',subject=subject,status='current',docStatus='final',date=measured,
             author=[{'reference':'Practitioner/demo'}],identifier=[{'system':LOCAL,'value':STUDY+'|'+VERSION},
             {'system':LOCAL+':site_zone','value':anchors['site_zone']},*[{'system':LOCAL+':'+k,'value':v} for k,v in anchors['events'].items()]],content=[{'attachment':{'title':'Synthetic signed screening anchor record'}}])
    if branch not in {None,'adult','adolescent','raised_total'}:
        doc=add('DocumentReference','pathology',status='current',docStatus='final',date=measured,subject=subject,author=[{'reference':'Practitioner/demo'}],content=[{'attachment':{'title':'Synthetic clinician branch assessment'}}])
        for dx,value in [('hcc',hcc),('liver_met',False),('gilbert',branch=='gilbert')]:
            anchors['conditions'][dx]=add('Observation','dx-'+dx,status='final',subject=subject,encounter=visit,code=cc(LOCAL,dx),
                 performer=[{'reference':'Practitioner/demo'}],effectiveDateTime=measured,issued=measured,valueBoolean=value,derivedFrom=[{'reference':doc}])
    spcodes=set(); results=[]
    def measurement(m,v,ul):
        code,sp,kind=MEASURES[m]
        specimen={}
        if sp:
            if sp not in spcodes:
                add('Specimen',sp,type=cc(MATERIAL,sp),subject=subject,status='available')
                spcodes.add(sp)
            specimen={'specimen':{'reference':f'Specimen/{sp}/_history/1'}}
        unit=next(iter(UNITS[kind])); limits={} if ul is None else {'referenceRange':[{'high':quantity(ul,unit)}]}
        if m=='child_gfr':limits['method']=cc(LOINC,'LA18032-5')
        code=add('Observation',m,status='final',code=cc(LOINC,code),subject=subject,encounter=visit,
                 effectiveDateTime=measured,issued=measured,valueQuantity=quantity(v,unit),**specimen,**limits)
        results.append({'reference':code})
    if branch=='raised_total':measurement('total_bili',2,1)
    ul=10 if relative else None
    bound=Decimal(target)*(ul if relative else 1)
    difference=(1 if (pass_test and op=='gt') else 0) if pass_test else (-1 if op=='ge' else 0 if op=='gt' else 1)
    measurement(name,float(bound+difference),ul)
    add('DiagnosticReport','labs',subject=subject,encounter=visit,status='final',issued=measured,performer=[{'reference':'Organization/site-lab'}],result=results)
    bundle={'resourceType':'Bundle','type':'collection','entry':[{'resource':r} for r in resources]}
    return bundle,anchors

def run_checks():
    checks=[]
    def check(leaf,label,b,a,expected):
        r=evaluate(leaf,b,a)
        if r['state']=='MET':
            assert any(x.startswith('Observation/') for x in r['evidence']) and any(x.startswith('DiagnosticReport/') for x in r['evidence'])
        checks.append({'criterion':'I08/'+leaf,'case':label,'expected':expected,'actual':r['state']})
    for leaf in LEAVES:
        for passed in (True,False):
            b,a=synthetic(leaf,passed);check(leaf,('qualifying value' if passed else 'outside threshold'),b,a,'MET' if passed else 'NOT_MET')
    def target(b,kind,id=None):
        return next(x['resource'] for x in b['entry'] if x['resource']['resourceType']==kind and (not id or x['resource']['id']==id.replace('_','-')))
    def mutate(leaf,label,kind,id,fields,expected='MISSING_DATA'):
        b,a=synthetic(leaf);r=target(b,kind,id)
        for k,v in fields.items():
            if v is None:r.pop(k,None)
            else:r[k]=v
        check(leaf,label,b,a,expected)
    for label,fields in [
        ('wrong patient',{'subject':{'reference':'Patient/other'}}),('wrong encounter',{'encounter':{'reference':'Encounter/other'}}),
        ('future issuance',{'issued':'2026-06-16T16:00:00Z'}),('future version',{'meta':{'versionId':'1','lastUpdated':'2026-07-01T00:00:00Z'}}),
        ('outside screening',{'effectiveDateTime':'2026-04-01T12:00:00Z'}),('unverified result',{'status':'preliminary'}),
        ('conflicting value',{'valueString':'2.8'}),('no specimen',{'specimen':None}),
        ('wrong specimen version',{'specimen':{'reference':'Specimen/SER/_history/2'}}),
        ('unknown units',{'valueQuantity':{'value':2.8,'system':UCUM,'code':'mg/mmol'}}),
        ('unmapped local code',{'code':{'coding':[{'system':LOCAL,'code':'ALB'}]}}),
    ]:mutate('P001',label,'Observation','albumin',fields)
    mutate('P001','plasma not serum','Specimen','SER',{'type':{'coding':[{'system':MATERIAL,'code':'PLAS'}]}})
    mutate('P001','outside local laboratory','DiagnosticReport','labs',{'performer':[{'reference':'Organization/external'}]})
    mutate('P001','unlinked final report','DiagnosticReport','labs',{'result':[]})
    mutate('P007','unselected local age-/sex-specific range','Observation','ast',{'referenceRange':[{'appliesTo':[{'text':'Female'}],'high':{'value':10,'code':'U/L','system':UCUM}}]})
    mutate('P007','missing ULN','Observation','ast',{'referenceRange':None})
    mutate('P019','indexed clearance is not Cockcroft-Gault unindexed','Observation','adult_crcl',{'valueQuantity':{'value':60,'system':UCUM,'code':'mL/min/{1.73_m2}'}})
    mutate('P019','unspecified calculation method','Observation','adult_crcl',{'code':{'coding':[{'system':LOCAL,'code':'CrCl'}]}})
    mutate('P020','generic Schwartz without bedside method','Observation','child_gfr',{'method':None})
    mutate('P020','different Schwartz method','Observation','child_gfr',{'method':{'coding':[{'system':LOINC,'code':'LA18031-7'}]}})
    mutate('P020','adult age branch','Patient','p',{'birthDate':'1980-03-03'},'NOT_APPLICABLE')
    mutate('P020','patient turns 18 during screening','Patient','p',{'birthDate':'2008-06-14'})
    mutate('P007','ordinary liver context','Observation','dx-hcc',{'valueBoolean':False},'NOT_APPLICABLE')
    b,a=synthetic('P009');del a['conditions']['hcc'];check('P009','absence of HCC code is not an exclusion',b,a,'MISSING_DATA')
    b,a=synthetic('P017');target(b,'Observation','total_bili')['valueQuantity']['value']=1.5;check('P017','direct reflex not triggered at boundary',b,a,'NOT_APPLICABLE')
    b,a=synthetic('P017');s=deepcopy(target(b,'Specimen','SER'));s['id']='other';b['entry'].append({'resource':s})
    target(b,'Observation','direct_bili')['specimen']['reference']=ref(s);check('P017','fractionation from another specimen',b,a,'MISSING_DATA')
    b,a=synthetic('P002');o=target(b,'Observation','platelets');o['valueQuantity'].update(value=100,code='10*9/L');check('P002','cross-unit count',b,a,'MET')
    b,a=synthetic('P001');target(b,'Observation','albumin')['valueQuantity'].update(value=28,code='g/L');check('P001','cross-unit mass',b,a,'MET')
    b,a=synthetic('P001');o=deepcopy(target(b,'Observation','albumin'));o['id']='second';o['valueQuantity']['value']=2
    b['entry'].append({'resource':o});target(b,'DiagnosticReport','labs')['result'].append({'reference':ref(o)});check('P001','no automatic priority across discordant results',b,a,'MISSING_DATA')
    for when,expected in [('2026-05-19T07:00:00Z','MET'),('2026-05-19T06:59:59Z','MISSING_DATA')]:
        b,a=synthetic('P001')
        a['events'].update(consent='2026-05-18T10:00:00Z',screening_start='2026-05-18T11:00:00Z')
        target(b,'Encounter','v')['period']['start']=a['events']['screening_start']
        for rec in target(b,'DocumentReference','screen-anchors')['identifier']:
            for k,v in a['events'].items():
                if rec['system']==LOCAL+':'+k:rec['value']=v
        target(b,'Observation','albumin')['effectiveDateTime']=when
        check('P001','local screening D−28 start boundary '+when,b,a,expected)
    b,a=synthetic('P001');a.pop('site_zone');check('P001','site time zone unavailable',b,a,'MISSING_DATA')
    b,a=synthetic('P001');a['study']='other';check('P001','unrelated trial anchor',b,a,'MISSING_DATA')
    mutate('P020','conflicting second method','Observation','child_gfr',
           {'method':{'coding':[{'system':LOINC,'code':'LA18032-5'},{'system':LOCAL,'code':'alternate-method'}]}})
    return checks

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--leaf',choices=LEAVES);parser.add_argument('--packet',help='JSON object with bundle and anchors');args=parser.parse_args()
    if args.leaf:
        if args.packet:
            with open(args.packet) as f: context=json.load(f)
            b,a=context['bundle'],context['anchors']
        else:b,a=synthetic(args.leaf)
        print(json.dumps(evaluate(args.leaf,b,a),indent=2))
    else:
        result=run_checks();print(json.dumps(result,indent=2))
        raise SystemExit(any(c['expected']!=c['actual'] for c in result))
