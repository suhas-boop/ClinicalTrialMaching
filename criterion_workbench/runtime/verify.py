"""Frozen synthetic checks. Run from any directory with Python 3.10+."""
import json,subprocess,sys
from copy import deepcopy
from datetime import datetime
from unittest.mock import patch
from pathlib import Path
from screen import CATALOG,run,ref
from normalize import normalize,SOURCE,LOCAL
BASE=Path(__file__).resolve().parent
S='106S01';N='NEOK001-1';R='REC-1245-101'
CUTOFF='2026-05-01T19:00:00Z'
T='2026-05-01T09:00:00Z'
def resource(kind,id,**fields):
    return dict(resourceType=kind,id=id,meta={'versionId':'1','lastUpdated':T},**fields)
def box(study,born='1990-05-01'):
    pat=resource('Patient','demo',birthDate=born)
    visit=resource('Encounter','screen',status='finished',subject={'reference':'Patient/demo'},period={'start':T,'end':CUTOFF},identifier=[{'system':'urn:pocketmd:demo:screening-study','value':study}])
    return {'resourceType':'Bundle','type':'collection','entry':[{'resource':pat},{'resource':visit}]}
def add(b,fact,v,minute=0,unit='ms'):
    i=str(len(b['entry']));visit=b['entry'][1]['resource'];pid=visit['subject'];t=f'2026-05-01T10:{minute:02}:00Z';spec=CATALOG[fact]
    doc=resource('DocumentReference','doc'+i,status='current',subject=pid,date=t,type={'text':'synthetic assessment'},content=[{'attachment':{'contentType':'text/plain','title':'synthetic fixture'}}])
    ob=resource('Observation','obs'+i,status='final',subject=pid,encounter={'reference':'Encounter/screen'},effectiveDateTime=t,issued=t,derivedFrom=[{'reference':ref(doc)}],code={'coding':[{'system':spec['system'],'code':spec['code']}]})
    if fact=='qtcf':ob['valueQuantity']={'value':v,'code':unit,'system':'http://unitsofmeasure.org'}
    elif spec.get('type') in ('integer','percentage'):ob['valueInteger']=v
    else:ob['valueBoolean']=v
    if spec.get('required_role'):
        role=resource('PractitionerRole','role'+i,active=True,identifier=[{'system':'urn:pocketmd:demo:role-study','value':visit['identifier'][0]['value']}],period={'start':T},code=[{'coding':[{'system':'urn:pocketmd:demo:study-roles','code':spec['required_role']}]}])
        ob['performer']=doc['author']=[{'reference':ref(role)}];b['entry'].append({'resource':role})
    b['entry'].extend([{'resource':doc},{'resource':ob}]);return ob
def checks():
    cases=[]
    def expect(study,short,b,want,label):
        result=run(study,b,'demo','screen',CUTOFF)['criteria'][study+'-'+short]
        assert result['state']==want,(label,result)
        if want in ('MET','NOT_MET'):assert result['evidence']
        cases.append({'study':study,'criterion':short,'case':label,'expected':want,'actual':result['state']})
    for dob,want in [('2008-05-01','MET'),('2008-05-02','NOT_MET'),('2008','MISSING_DATA')]:
        expect(N,'I02',box(N,dob),want,'age '+dob)
    def numeric(study,id,values,want,minutes=None):
        b=box(study)
        for i,v in enumerate(values):add(b,'qtcf',v,(minutes or list(range(len(values))))[i])
        expect(study,id,b,want,'QTcF '+str(values)+' '+str(minutes));return b
    numeric(S,'I15',[469],'MET');b=numeric(S,'I15',[470],'NOT_MET');numeric(S,'I15',[],'MISSING_DATA')
    c=box(S);add(c,'qtcf',0.47,unit='s');expect(S,'I15',c,'NOT_MET','UCUM seconds')
    for v,expected in [([469]*3,'MET'),([470]*3,'NOT_MET'),([469,470,471],'AUTHORING_HOLD'),([460,461],'MISSING_DATA')]:numeric(N,'E15',v,expected)
    numeric(N,'E15',[469]*3,'MISSING_DATA',[0,1,11])
    for n,vals,history,want in [(1,[470],False,'MET'),(2,[470],True,'NOT_MET'),(3,[470],None,'MISSING_DATA'),(4,[471]*3,False,'NOT_MET'),(5,[471,469,469],False,'AUTHORING_HOLD')]:
        b=box(R)
        for i,v in enumerate(vals):add(b,'qtcf',v,i)
        if history is not None:add(b,'long_qt_history',history)
        expect(R,'E07',b,want,'REC history + screen '+str(n))
    for value,want in [(0,'MET'),(1,'MET'),(2,'NOT_MET'),(None,'MISSING_DATA')]:
        b=box(N)
        if value is not None:add(b,'ecog',value)
        expect(N,'I06',b,want,'ECOG '+str(value))
    b=box(S);score=add(b,'ecog',2);expect(S,'I03',b,'INVESTIGATOR_ACTIONS','obtain medical monitor decision')
    a=add(b,'ecog2_clearance',True,1);a['focus']=[{'reference':ref(score)}];expect(S,'I03',b,'MET','medical monitor signed agreement')
    a['valueBoolean']=False;expect(S,'I03',b,'NOT_MET','medical monitor declined')
    a['focus']=[{'reference':'Observation/other/_history/1'}];expect(S,'I03',b,'MISSING_DATA','agreement for another assessment')
    for dob,f,v,want in [('2000-01-01','ecog',2,'NOT_MET'),('2011-01-01','lansky',70,'MET'),('2010-05-01','karnofsky',60,'NOT_MET'),('2011-01-01','ecog',0,'MISSING_DATA')]:
        b=box(R,dob);add(b,f,v);expect(R,'I05',b,want,'REC scale '+dob+f)
    for id,f,positive in [('I05','appropriate_candidate',True),('E06','severe_preexisting',False),('E12','substance_abuse',False),('E15','major_ventricular_arrhythmia_history',False)]:
        for v in [None,True,False]:
            b=box(S)
            if v is not None:add(b,f,v)
            want=('INVESTIGATOR_ACTIONS' if CATALOG[f].get('required_role') else 'MISSING_DATA') if v is None else ('MET' if v==positive else 'NOT_MET')
            expect(S,id,b,want,'explicit assessment '+str(v))
    for id,left,right in [('E07','interstitial_pneumonitis_history','pulmonary_fibrosis_history'),('E16','congenital_longqt','family_congenital_longqt')]:
        for l,r,want in [(False,False,'MET'),(False,None,'MISSING_DATA'),(None,True,'NOT_MET'),(True,False,'NOT_MET')]:
            b=box(S)
            if l is not None:add(b,left,l)
            if r is not None:add(b,right,r)
            expect(S,id,b,want,'history '+str((l,r)))
    for defect in ['source-patient','source-pin','source-future','unit','generic-method','future-result','other-visit']:
        b=box(S);o=add(b,'qtcf',460);doc=b['entry'][2]['resource']
        if defect=='source-patient':doc['subject']={'reference':'Patient/other'}
        if defect=='source-pin':o['derivedFrom'][0]['reference']=ref(doc)[:-1]+'2'
        if defect=='source-future':doc['date']='2026-05-02T00:00:00Z'
        if defect=='unit':o['valueQuantity']['code']='min'
        if defect=='generic-method':o['code']['coding'][0]['code']='QTc'
        if defect=='future-result':o['issued']='2026-05-02T00:00:00Z'
        if defect=='other-visit':o['encounter']['reference']='Encounter/other'
        expect(S,'I15',b,'MISSING_DATA',defect)
    b=box(N);o=add(b,'ecog',1);o['code']['coding']=[{'system':SOURCE,'code':LOCAL}]
    expect(N,'I06',b,'MISSING_DATA','local code before mapping')
    b2,audit=normalize(b);assert audit and len(b2['entry'][-1]['resource']['code']['coding'])==2
    expect(N,'I06',b2,'MET','mapped local ECOG');assert normalize(b2)[0]==b2
    o['code']['coding'].append({'system':'http://loinc.org','code':'other'})
    try:normalize(b)
    except ValueError:pass
    else:raise AssertionError('accepted conflicting codes')
    for case,want in [('all-met',['MET','MET','MET']),('localized',['NOT_MET',None,None])]:
        d=json.loads(subprocess.check_output([sys.executable,str(BASE/'michigan.pyz'),'--demo',case]))
        for i,expected in enumerate(want,1):
            if expected is None:continue
            actual=d['outcomes'].get(f'MI-LMS-0{i}');assert actual==expected,(case,actual)
            cases.append({'study':'NCT05653388','criterion':f'MI-LMS-0{i}','case':case,'expected':expected,'actual':actual})
    birthday_chart=box(N, '2008-05-02')
    def time_case(label, bundle, criterion, expected, cutoff=None, zone=None):
        result=run(N, bundle, 'demo', 'screen', cutoff, timezone_name=zone)
        actual=result['criteria'][criterion]['state']
        assert actual==expected,(label,actual)
        cases.append({'study':N,'criterion':criterion,'case':label,'expected':expected,'actual':actual})
        return result
    class FrozenClock(datetime):
        @classmethod
        def now(cls,tz=None):
            when=datetime.fromisoformat('2026-05-02T00:30:00+00:00')
            return when.astimezone(tz) if tz else when.astimezone().replace(tzinfo=None)
    with patch('screen.datetime',FrozenClock):
        local=time_case('run-day before birthday in Los Angeles',birthday_chart,N+'-I02','NOT_MET',zone='America/Los_Angeles')
        utc=time_case('run-day birthday in UTC after an earlier encounter',birthday_chart,N+'-I02','MET',zone='UTC')
        assert local['screening_date']=='2026-05-01' and utc['screening_date']=='2026-05-02'
        assert local['as_of_source']==utc['as_of_source']=='run_clock'
    historical=time_case('explicit cutoff replays prior day',birthday_chart,N+'-I02','NOT_MET','2026-05-01T23:59:59Z')
    assert historical['as_of_source']=='explicit'
    same_day=box(N)
    ob=add(same_day,'ecog',1)
    ob['issued']='2026-05-01T11:00:00Z'
    time_case('later same-day release unavailable',same_day,N+'-I06','MISSING_DATA','2026-05-01T10:59:59Z')
    time_case('same-day release now visible',same_day,N+'-I06','MET','2026-05-01T11:00:00Z')
    from onboarding import test_cycle,validate,packet_answers,install
    from tempfile import TemporaryDirectory
    onboard=json.loads((BASE/'demo-sotio-onboarding.json').read_text())
    def audit_case(label,actual,want):
        assert actual==want,(label,actual,want)
        cases.append({'study':S,'criterion':'onboarding','case':label,'expected':want,'actual':actual})
    audit_case('synthetic Nov 19 onboarding plus seven days',test_cycle(onboard)['cycle_1_day_1'],'2026-11-26')
    audit_case('re-screen later with original onboarding',test_cycle(onboard,'2026-11-27T20:00:00Z')['cycle_1_day_1'],'2026-11-26')
    spring={**onboard,'uploaded_at':'2026-03-02T07:30:00Z'}
    audit_case('convert upload instant to the site day before adding calendar days',test_cycle(spring)['cycle_1_day_1'],'2026-03-08')
    audit_case('ordinary onboarding has no simulated first cycle',test_cycle({**onboard,'test_cycle_start_offset_days':None}),None)
    b=box(S);add(b,'qtcf',469)
    # At screening the same ECG meets the numeric threshold in both runs.
    # Only the simulated calendar changes whether its date precedes cycle 1.
    for uploaded,want in [('2026-04-24T09:00:00-07:00','MISSING_DATA'),('2026-04-25T09:00:00-07:00','MET')]:
        cfg={**onboard,'uploaded_at':uploaded}
        result=run(S,b,'demo','screen',CUTOFF,onboarding=cfg)
        assert result['mode']=='simulation' and 'first_dose' not in result['simulated_schedule']
        audit_case('ECG with simulated cycle based on '+uploaded,result['criteria'][S+'-I15']['state'],want)
    try:
        run(S,b,'demo','screen',CUTOFF,onboarding=onboard)
    except ValueError:
        audit_case('pre-upload replay cannot use the assumption',True,True)
    else:raise AssertionError('Future onboarding record used.')
    try:
        validate(onboard,N)
    except ValueError:
        audit_case('another trial cannot reuse this profile',True,True)
    else:raise AssertionError('Study mismatch accepted.')
    answered=deepcopy(onboard)
    answered['questions'][1].update(answer='Synthetic example response.',authority='Test coordinator',decision_date='2026-11-19')
    audit_case('answer is scoped to the rule and amendment',packet_answers(validate(answered,S),'106S01-I18')[0]['answer'],'Synthetic example response.')
    audit_case('unrelated rule receives no answer',packet_answers(answered,'106S01-I15'),[])
    with TemporaryDirectory() as td:
        path=Path(td)/'onboarding.json'
        install(path,answered)
        retried=install(path,{**onboard,'uploaded_at':'2026-11-21T00:00:00Z'})
        audit_case('retry retains original upload and recorded answer',retried==answered,True)
    for id, facts in [('I08',{'anc':1.5,'platelets':100,'hemoglobin':9}),('I12',{'albumin':3})]:
        def panel(change=None,delta=0,skip=None,late=False):
            b=box(S)
            for f,v in facts.items():
                if f==skip:continue
                ob=add(b,f,False)
                ob.pop('valueBoolean')
                ob['valueQuantity']={'system':'http://unitsofmeasure.org','code':CATALOG[f]['canonical_unit'],'value':v+(delta if f==change else 0)}
                if late:ob['issued']='2026-05-08T00:00:00Z'
            return b
        first=next(iter(facts))
        def labcheck(label,b,date_1,expected):
            cfg={**onboard,'uploaded_at':date_1+'T00:00:00Z','timezone':'UTC'}
            result=run(S,b,'demo','screen','2026-05-09T00:00:00Z',onboarding=cfg)
            got=result['criteria'][S+'-'+id]['state']
            assert got==expected,(label,got)
            cases.append(dict(study=S,criterion=id,case=label,expected=expected,actual=got))
        labcheck('inclusive threshold at seven days',panel(),'2026-05-01','MET')
        labcheck('out of window at eight days',panel(),'2026-05-02','MISSING_DATA')
        labcheck('release on cycle day one',panel(late=True),'2026-05-01','MISSING_DATA')
        labcheck('missing component',panel(skip=first),'2026-05-01','MISSING_DATA')
        for f in facts:labcheck('low '+f,panel(f,-0.1),'2026-05-01','NOT_MET')
        b=panel();o=b['entry'][-1]['resource'];o['valueQuantity']['value']*=10;o['valueQuantity']['code']='g/L'
        labcheck('equivalent mass units',b,'2026-05-01','MET')
        o['valueQuantity']['code']='mmol/L'
        labcheck('incompatible unit',b,'2026-05-01','MISSING_DATA')
    cfg={**onboard,'uploaded_at':'2026-04-24T00:00:00Z','timezone':'UTC'}
    for label,event,want in [('14 days','2026-04-17T08:00:00Z','NOT_MET'),('15 days','2026-04-16T08:00:00Z','MET'),('same day','2026-05-01T08:00:00Z','MISSING_DATA'),('explicit negative',False,'MET'),('no history',None,'MISSING_DATA')]:
        b=box(S)
        if event is not None:
            ob=add(b,'rbc_review',False)
            if event:
                ob.pop('valueBoolean');ob['valueDateTime']=event
        got=run(S,b,'demo','screen',CUTOFF,onboarding=cfg)['criteria']['106S01-E04']['state']
        assert got==want,(label,got)
        cases.append(dict(study=S,criterion='E04',case=label,expected=want,actual=got))
    cfg={**cfg,'uploaded_at':'2026-05-01T00:00:00Z'}
    b=box(S);add(b,'rbc_review',False)
    got=run(S,b,'demo','screen',CUTOFF,onboarding=cfg)['criteria']['106S01-E04']['state']
    assert got=='MISSING_DATA'
    cases.append(dict(study=S,criterion='E04',case='history ends before projected start',expected='MISSING_DATA',actual=got))
    def prognosis(v, unit='mo', comparator=None):
        b=box(S)
        o=add(b,'estimated_survival',False)
        del o['valueBoolean']
        o['valueQuantity']={'value':v,'code':unit,'system':'http://unitsofmeasure.org'}
        if comparator:o['valueQuantity']['comparator']=comparator
        return b
    expect(S,'I04',box(S),'INVESTIGATOR_ACTIONS','investigator estimate absent')
    for v,unit,op,want in [(3,'mo',None,'MET'),(2.9,'mo',None,'NOT_MET'),(0.25,'a',None,'MET'),
                            (3,'mo','>=','MET'),(3,'mo','<','NOT_MET'),(3,'mo','<=','INVESTIGATOR_ACTIONS'),
                            (2,'mo','>','INVESTIGATOR_ACTIONS'),(90,'d',None,'MISSING_DATA')]:
        expect(S,'I04',prognosis(v,unit,op),want,f'{op or "exact"} {v} {unit}')
    b=prognosis(3)
    b['entry'][2]['resource']['identifier'][0]['value']='other-study'
    expect(S,'I04',b,'MISSING_DATA','wrong study assignment')
    b=prognosis(3)
    b['entry'][3]['resource']['author']=[]
    expect(S,'I04',b,'MISSING_DATA','unverified signer')
    b=prognosis(3)
    o=deepcopy(b['entry'][-1]['resource']);o['id']='conflict';o['valueQuantity']['value']=2
    b['entry'].append({'resource':o})
    expect(S,'I04',b,'INVESTIGATOR_ACTIONS','conflicting screening estimates')
    for bundle,state,status in [(box(S),'INVESTIGATOR_ACTIONS','ACTION_REQUIRED'),
                                (prognosis(3),'MET','COMPLETED'),
                                (prognosis(2),'NOT_MET','COMPLETED'),
                                (prognosis(90,'d'),'MISSING_DATA','VERIFY_EVIDENCE')]:
        result=run(S,bundle,'demo','screen',CUTOFF)['criteria'][S+'-I04']
        workflow=result['assessment_workflow']
        assert workflow['category']=='INVESTIGATOR_ACTIONS' and workflow['required_role']=='investigator'
        assert workflow['status']==status and result['state']==state
        cases.append(dict(study=S,criterion='I04',case='assessment workflow '+state,expected=status,actual=workflow['status']))
    for attestation, expected_state in [(None,'INVESTIGATOR_ACTIONS'),(True,'MET'),(False,'NOT_MET')]:
        b=box(S)
        if attestation is not None:add(b,'appropriate_candidate',attestation)
        record=run(S,b,'demo','screen',CUTOFF)['criteria'][S+'-I05']
        workflow=record['assessment_workflow']
        want='ACTION_REQUIRED' if attestation is None else 'COMPLETED'
        assert (record['state'],workflow['category'],workflow['required_role'],workflow['status'])==(expected_state,'INVESTIGATOR_ACTIONS','investigator',want)
        cases.append(dict(study=S,criterion='I05',case='candidacy judgment '+str(attestation),expected=want,actual=workflow['status']))
    from check_prescreen import prescreen_checks
    cases.extend(prescreen_checks())
    from check_agreement import agreement_checks, review_handoff_checks
    cases.extend(agreement_checks())
    cases.extend(review_handoff_checks())
    return cases
if __name__=='__main__':print(json.dumps(checks(),indent=2))
