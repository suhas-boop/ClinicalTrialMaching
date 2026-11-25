"""Research evaluator for frozen, normalized FHIR R4 collection snapshots."""
import argparse
import calendar
import json
import operator
import re
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from evidence import instant, ref, single, decision, meets_inclusive_minimum
from agreement import evaluate_agreement
from prescreen import evaluate_tissue_assay, is_prescreening
from onboarding import study_inventory, test_cycle, validate as validate_onboarding

HERE = Path(__file__).resolve().parent
def load(name):
    return json.loads((HERE/name).read_text())
RULES = load('rules.json')
CATALOG_DATA = load('catalog.json')
CATALOG = {c['key']: c for c in CATALOG_DATA['mappings']}
COMPARE = {'lt': operator.lt, 'le': operator.le, 'ge': operator.ge}

def __getattr__(name):
    if name == 'INVENTORY':
        return study_inventory()
    raise AttributeError(name)

def screening_cutoff(as_of=None, timezone_name=None):
    """Resolve the evaluation clock once. Explicit timestamps retain their offset by default."""
    zone = ZoneInfo(timezone_name) if timezone_name else None
    if as_of is None:
        now = datetime.now(zone) if zone else datetime.now().astimezone()
        return now.isoformat()
    timestamp = instant(as_of)
    return timestamp.astimezone(zone).isoformat() if zone else as_of

class Snapshot:
    def __init__(self,bundle,patient,study,encounter,cutoff):
        self.cutoff=instant(cutoff)
        self.study=study
        if bundle.get('resourceType')!='Bundle' or bundle.get('type')!='collection':
            raise ValueError('Provide a normalized collection Bundle.')
        self.resources={}
        for item in bundle.get('entry',[]):
            r=item['resource']
            if instant(r['meta']['lastUpdated'])>self.cutoff: continue
            path=r['resourceType']+'/'+r['id']
            if path in self.resources: raise ValueError('Provide one as-of resource version per logical ID.')
            if r.get('implicitRules') or r.get('modifierExtension'): raise ValueError('Verify resource modifier semantics before use.')
            if not r['meta'].get('versionId'): raise ValueError('Source version missing.')
            self.resources[path]=r
        self.patient=self.resources['Patient/'+patient]
        self.encounter=self.resources['Encounter/'+encounter]
        self.person='Patient/'+patient
        self.visit='Encounter/'+encounter
        e=self.encounter
        if e['subject']['reference']!=self.person or e.get('status') not in ('in-progress','finished'):
            raise ValueError('Screening encounter does not establish this patient and visit.')
        if [x['value'] for x in e.get('identifier',[]) if x.get('system')=='urn:pocketmd:demo:screening-study']!=[study]:
            raise ValueError('Supply a screening encounter verified for this study.')
        self.start=instant(e['period']['start'])
        self.end=min(instant(e['period']['end']),self.cutoff) if e['period'].get('end') else self.cutoff
        if self.start>self.end: raise ValueError('The screening encounter is outside the cutoff.')
        self.evidence=[ref(self.patient),ref(e)]

    def readings(self,fact,window=None):
        spec=CATALOG[fact]
        rows=[]
        for r in self.resources.values():
            if r.get('resourceType')!='Observation' or r.get('subject',{}).get('reference')!=self.person or r.get('encounter',{}).get('reference')!=self.visit: continue
            if not any(c.get('system')==spec['system'] and c.get('code')==spec['code'] for c in r['code'].get('coding',[])):continue
            if r.get('status') in ('cancelled','entered-in-error'): continue
            if 'dataAbsentReason' in r:raise ValueError('Obtain a documented value for '+fact)
            if any(c.get('system')==spec['system'] and c.get('code')!=spec['code'] for c in r['code'].get('coding',[])):raise ValueError('Resolve contradictory coding before using this observation.')
            if instant(r['issued'])>self.cutoff:continue
            t=instant(r['effectiveDateTime'])
            if not self.start<=t<=self.end: continue
            if window:
                anchor,zone,days=window
                dates=[t,instant(r['issued'])]
                if not all(1 <= (anchor-d.astimezone(zone).date()).days <= days for d in dates):continue
            if r.get('status') not in ('final','amended','corrected') or t>instant(r['issued']):
                raise ValueError('Verify the final assessment and release time.')
            link=single(r.get('derivedFrom',[]),'Provide one exact source document for the assessment.')['reference']
            doc=self.resources.get(link.split('/_history/')[0])
            if not doc or doc['resourceType']!='DocumentReference' or ref(doc)!=link or doc.get('subject',{}).get('reference')!=self.person or doc.get('status')!='current':
                raise ValueError('Verify the document version and its patient.')
            evidence=[ref(r),link]
            if doc.get('date') and instant(doc['date'])>self.cutoff:
                raise ValueError('The source document was unavailable at screening.')
            if spec.get('required_role'):
                actor=single(r.get('performer',[]),'Verify the designated assessor.')['reference']
                role=self.resources.get(actor.split('/_history/')[0])
                if not role or role['resourceType']!='PractitionerRole' or ref(role)!=actor or role.get('active') is not True:
                    raise ValueError('Verify the versioned assessor role.')
                if actor not in [a.get('reference') for a in doc.get('author',[])]:
                    raise ValueError('Verify the signing assessor.')
                codes={v.get('code') for cc in role.get('code',[]) for v in cc.get('coding',[]) if v.get('system')=='urn:pocketmd:demo:study-roles'}
                assignments=[i['value'] for i in role.get('identifier',[]) if i.get('system')=='urn:pocketmd:demo:role-study']
                period=role.get('period',{})
                if spec['required_role'] not in codes or assignments!=[self.study] or instant(period['start'])>t or (period.get('end') and instant(period['end'])<t):
                    raise ValueError('Verify the assessor assignment for this study and date.')
                evidence.append(actor)
            if spec.get('type') in ('integer','percentage'):
                v=r['valueInteger']
                allowed=range(6) if spec['type']=='integer' else range(0,101,10)
                if type(v) is not int or v not in allowed:raise ValueError('Verify instrument and score.')
            elif spec.get('type')=='transfusion_review':
                if 'valueDateTime' in r and 'valueBoolean' not in r:
                    v=instant(r['valueDateTime'])
                    if v>t:raise ValueError('Transfusion occurred after the history review.')
                elif r.get('valueBoolean') is False and 'valueDateTime' not in r:
                    v=None
                else:raise ValueError('Obtain the last actual red-cell transfusion or a documented negative history.')
            elif spec.get('type')=='duration_estimate':
                q=r['valueQuantity']
                if sum(key.startswith('value') for key in r)!=1 or q.get('system')!='http://unitsofmeasure.org' or q.get('code') not in spec['scales']:
                    raise ValueError('Verify the estimate and its duration unit.')
                comparator=q.get('comparator','=')
                if comparator not in ('<','<=','>','>=','=') or ('comparator' in q and comparator=='=') or type(q.get('value')) not in (int,float):
                    raise ValueError('Verify the numeric estimate and comparator.')
                duration=Decimal(str(q['value']))*spec['scales'][q['code']]
                if not duration.is_finite() or duration<0 or (duration==0 and comparator=='<'):
                    raise ValueError('Invalid duration estimate.')
                v=(comparator,duration)
            elif spec.get('type')=='lab_quantity':
                q=r['valueQuantity']
                if q.get('system')!='http://unitsofmeasure.org' or q.get('code') not in spec['scales'] or 'comparator' in q:
                    raise ValueError('Verify unit and exact value for '+fact)
                if type(q.get('value')) not in (int,float):
                    raise ValueError('Verify numeric result for '+fact)
                v=Decimal(str(q['value']))*Decimal(str(spec['scales'][q['code']]))
                if not v.is_finite() or v<0:raise ValueError('Invalid result for '+fact)
            elif fact=='qtcf':
                q=r['valueQuantity']
                if q.get('system')!=spec['unit_system'] or q.get('code') not in spec['unit_codes'] or 'comparator' in q:
                    raise ValueError('Provide an exact QTcF with verified UCUM units.')
                v=q['value']
                if isinstance(v,bool) or not isinstance(v,(int,float)):raise ValueError('Invalid QTcF quantity.')
                v=Decimal(str(v))*(1000 if q['code']=='s' else 1)
                if not v.is_finite() or v<=0:raise ValueError('Invalid QTcF quantity.')
            else:
                v=r['valueBoolean']
                if type(v) is not bool: raise ValueError('An explicit history assessment is required.')
            if fact=='ecog2_clearance':
                score_ref=single(r.get('focus',[]),'Link approval to the ECOG 2 assessment.')['reference']
                linked=self.resources.get(score_ref.split('/_history/')[0])
                if not linked or linked.get('resourceType')!='Observation' or ref(linked)!=score_ref or linked.get('subject',{}).get('reference')!=self.person or linked.get('encounter',{}).get('reference')!=self.visit or linked.get('valueInteger')!=2 or not any(c.get('system')==CATALOG['ecog']['system'] and c.get('code')==CATALOG['ecog']['code'] for c in linked.get('code',{}).get('coding',[])) or linked.get('status') not in ('final','corrected','amended') or instant(linked['issued'])>t:
                    raise ValueError('Agreement must concern this verified ECOG 2 assessment.')
                evidence.append(score_ref)
            rows.append((t,v,evidence))
        return sorted(rows,key=lambda row:row[0])

def eval_rule(chart,rule,cycle=None,site_zone=None):
    evidence=list(chart.evidence)
    def value(fact):
        rows=chart.readings(fact)
        for _,_,refs in rows:evidence.extend(refs)
        values={r[1] for r in rows}
        if len(values)>1:raise ValueError('Conflicting screening evidence for '+fact)
        return next(iter(values),None)
    def missing(fact):
        state='INVESTIGATOR_ACTIONS' if CATALOG[fact].get('required_role') else 'MISSING_DATA'
        return decision(state,CATALOG[fact]['meaning']+' required.',evidence)
    kind=rule.get('kind')
    if kind=='prescreen_tissue_assay':
        return evaluate_tissue_assay(chart, rule, CATALOG_DATA['prescreen_assays'][rule['contract']], site_zone)
    if is_prescreening(chart.encounter):
        return decision('MISSING_DATA','This assessment requires the formal screening encounter.',chart.evidence)
    if kind=='respondent_agreement':
        form = CATALOG_DATA['agreement_forms'][rule['contract']]
        return evaluate_agreement(chart, rule, form, site_zone)
    if kind=='duration_minimum':
        threshold=Decimal(str(rule['minimum_months']))
        rows=chart.readings(rule['fact'])
        if not rows:return missing(rule['fact'])
        states=set()
        for _,(op,n),refs in rows:
            evidence.extend(refs)
            resolved=meets_inclusive_minimum(op,n,threshold)
            states.add({True:'MET',False:'NOT_MET',None:'INVESTIGATOR_ACTIONS'}[resolved])
        if len(states)!=1 or 'INVESTIGATOR_ACTIONS' in states:
            return decision('INVESTIGATOR_ACTIONS','Clarify whether the investigator estimate meets the minimum.',evidence)
        return decision(states.pop(),'Compared the signed investigator estimate with the inclusive minimum in months.',evidence)
    if kind=='last_event_exclusion':
        if not cycle:return decision('MISSING_DATA','Supply cycle 1 day 1.',evidence)
        anchor=date.fromisoformat(cycle['cycle_1_day_1'])
        zone=ZoneInfo(cycle['timezone'])
        rows=chart.readings(rule['fact'])
        previous=None
        documented_inside=False
        covered=False
        for assessed,event,refs in rows:
            evidence.extend(refs)
            if previous is not None and (event is None or event<previous):
                return decision('MISSING_DATA','Reconcile inconsistent transfusion histories.',evidence)
            previous=event
            days=(anchor-event.astimezone(zone).date()).days if event else None
            if days is not None and 1<=days<=rule['days']:documented_inside=True
            if assessed.astimezone(zone).date()>=anchor and (days is None or days>rule['days']):covered=True
        if documented_inside:return decision('NOT_MET','Confirmed red-cell transfusion within the inclusive lookback.',evidence)
        if covered:return decision('MET','Documented history covers the pre-cycle window.',evidence)
        return decision('MISSING_DATA','Obtain history covering the pre-cycle window or clarify same-day ordering.',evidence)
    if kind=='all_minimum_labs':
        if not cycle:
            return decision('MISSING_DATA','Supply the cycle 1 start date for the screening lab window.',evidence)
        window=(date.fromisoformat(cycle['cycle_1_day_1']),ZoneInfo(cycle['timezone']),rule['window_days'])
        missing=[]
        for fact,minimum in rule['minimum'].items():
            try:
                rows=chart.readings(fact,window)
            except (KeyError,TypeError,ValueError,ArithmeticError):
                missing.append(fact)
                continue
            statuses={v>=Decimal(str(minimum)) for _,v,_ in rows}
            for _,_,refs in rows:evidence.extend(refs)
            if statuses=={False}:
                return decision('NOT_MET',fact+' below the protocol minimum.',evidence)
            if statuses!={True}:missing.append(fact)
        if missing:return decision('MISSING_DATA','Obtain or reconcile in-window '+', '.join(missing)+'.',evidence)
        return decision('MET','All required lab results meet their inclusive thresholds.',evidence)
    if kind=='boolean':
        v=value(rule['fact'])
        if v is None:return missing(rule['fact'])
        return decision('MET' if v==rule['expected'] else 'NOT_MET',CATALOG[rule['fact']]['meaning'],evidence)
    if kind=='exclude_any':
        unresolved=[]
        for f in rule['facts']:
            v=value(f)
            if v is True:return decision('NOT_MET',CATALOG[f]['meaning'],evidence)
            if v is None:unresolved.append(f)
        if unresolved:return decision('MISSING_DATA','Obtain explicit history for '+', '.join(unresolved),evidence)
        return decision('MET','Both history reviews explicitly negative.',evidence)
    if kind=='performance':
        instrument='ecog'
        if rule.get('age_routing'):
            day=chart.start.date();dob=date.fromisoformat(chart.patient['birthDate'])
            if dob>day:raise ValueError('Verify date of birth.')
            age=day.year-dob.year-((day.month,day.day)<(dob.month,dob.day))
            if dob.month==2 and dob.day==29 and (day.month,day.day)==(2,28) and not calendar.isleap(day.year) and day.year-dob.year in (16,18):return decision('AUTHORING_HOLD','Confirm birthday convention for instrument selection.',evidence)
            if age<12:return decision('AUTHORING_HOLD','Below studied adolescent age. Evaluate cohort applicability first.',evidence)
            if age<18: instrument='lansky' if age<16 else 'karnofsky'
        score=value(instrument)
        if score is None:return missing(instrument)
        if instrument!='ecog':return decision('MET' if score>=70 else 'NOT_MET','Screening '+instrument+' score '+str(score),evidence)
        if rule.get('agreement') and score==rule['exception_score']:
            approved=value(rule['agreement'])
            if approved is None:return missing(rule['agreement'])
            return decision('MET' if approved else 'NOT_MET','Sponsor medical monitor disposition for ECOG 2.',evidence)
        return decision('MET' if score in rule['accepted'] else 'NOT_MET','Screening ECOG score '+str(score),evidence)
    if rule['fact']=='age':
        birth=chart.patient.get('birthDate','')
        if not re.fullmatch(r'\d{4}-\d\d-\d\d',birth):raise ValueError('Provide a complete verified birth date.')
        dob=date.fromisoformat(birth);day=chart.cutoff.date()
        if dob>day:raise ValueError('Birth date is after screening.')
        age=day.year-dob.year-((day.month,day.day)<(dob.month,dob.day))
        if dob.month==2 and dob.day==29 and not calendar.isleap(day.year) and (day.month,day.day)==(2,28) and day.year-dob.year==rule['threshold']:
            return decision('AUTHORING_HOLD','Confirm the applicable leap-day birthday convention.',evidence)
        return decision('MET' if age>=rule['threshold'] else 'NOT_MET',f'Age at screening was {age} completed years.',evidence)
    mode=rule['acquisitions']
    if mode=='screening_and_history':
        history=chart.readings('long_qt_history')
        hs={r[1] for r in history}
        for _,_,refs in history:evidence.extend(refs)
        if hs=={True}:return decision('NOT_MET','Documented personal history of long QT syndrome.',evidence)
    readings=chart.readings('qtcf')
    if cycle and rule.get('screen_before_cycle_start'):
        zone=ZoneInfo(cycle['timezone'])
        first_day=date.fromisoformat(cycle['cycle_1_day_1'])
        readings=[row for row in readings if row[0].astimezone(zone).date() < first_day]
        if not readings:
            return decision('MISSING_DATA','Obtain a screening ECG before the simulated cycle 1 start date.',evidence)
    for _,_,refs in readings:evidence.extend(refs)
    if not readings:return decision('MISSING_DATA','Obtain the study screening 12-lead QTcF.',evidence)
    answers=[COMPARE[rule['operator']](r[1],rule['threshold']) for r in readings]
    if mode=='triplicate':
        if len(readings)!=3:return decision('MISSING_DATA','Identify the three ECGs in the screening set.',evidence)
        times=[r[0] for r in readings]
        if min((b-a).total_seconds() for a,b in zip(times,times[1:]))<60 or (times[-1]-times[0]).total_seconds()>600:
            return decision('MISSING_DATA','Obtain a protocol-timed triplicate ECG set.',evidence)
    if mode=='single' and len(readings)!=1:return decision('MISSING_DATA','Identify the designated screening ECG.',evidence)
    if len(set(answers))>1:return decision('AUTHORING_HOLD','Screening QTcF readings cross the boundary. Obtain the governing interpretation.',evidence)
    if mode=='screening_and_history':
        if not answers[0]:
            if len(readings)!=3 or min((b[0]-a[0]).total_seconds() for a,b in zip(readings,readings[1:]))<60 or (readings[-1][0]-readings[0][0]).total_seconds()>1800:
                return decision('MISSING_DATA','Confirm the initial elevated QTcF with the two protocol-timed repeat ECGs.',evidence)
        elif hs!={False}:return decision('MISSING_DATA','Verify personal long QT syndrome history.',evidence)
    return decision('MET' if answers[0] else 'NOT_MET','Compared the source-linked screening QTcF in milliseconds.',evidence)

def grouped(states):
    outputs={name:[] for name in ('MET','NOT_MET','MISSING_DATA','INVESTIGATOR_ACTIONS','PATIENT_SURVEY')}
    holds={}
    for key,record in states.items():
        name=record['state']
        if name in outputs:outputs[name].append(key)
        else:holds[key]=record.get('reason',name)
    return {'outputs':outputs,'pipeline_holds':holds}

def run(study,bundle,patient,encounter,as_of=None,*,timezone_name=None,onboarding=None):
    inventory = study_inventory()
    if onboarding is not None:
        validate_onboarding(onboarding,study)
        timezone_name=timezone_name or onboarding['timezone']
    source = 'run_clock' if as_of is None else 'explicit'
    as_of = screening_cutoff(as_of, timezone_name)
    screening_day = instant(as_of).date().isoformat()
    cycle=test_cycle(onboarding,as_of) if onboarding is not None else None
    criteria=[r for r in inventory['criteria'] if r['study']==study]
    if not criteria:raise ValueError('Unknown study')
    results={}
    for row in criteria:
        key=row['id']
        if key not in RULES:
            results[key]=decision('AUTHORING_HOLD','No promoted rule in this runtime. See the numbered source packet.')
            continue
        try:
            chart=Snapshot(bundle,patient,study,encounter,as_of)
            results[key]=eval_rule(chart,RULES[key],cycle,timezone_name)
        except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
            results[key]=decision('MISSING_DATA','Evidence could not be verified: '+str(exc))
        workflow=RULES[key].get('assessment_workflow')
        if workflow:
            result=results[key]
            result['assessment_workflow']={**workflow,'status':{
                'MET':'COMPLETED','NOT_MET':'COMPLETED',
                'INVESTIGATOR_ACTIONS':'ACTION_REQUIRED','MISSING_DATA':'VERIFY_EVIDENCE'
            }[result['state']]}
    return {**({'mode':'simulation','simulated_schedule':cycle} if cycle else {}),'study':study,'as_of':as_of,'screening_date':screening_day,'as_of_source':source,'catalog':CATALOG_DATA['version'],'protocol_sha256':inventory['studies'][study]['protocol_sha256'],'patient':'Patient/'+patient,'criteria':results,**grouped(results)}

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('study',choices=study_inventory()['studies'])
    p.add_argument('--bundle',required=True,type=Path)
    p.add_argument('--patient',required=True)
    p.add_argument('--as-of',help='Optional replay cutoff. Use an offset timestamp, or a date for Michigan.')
    p.add_argument('--timezone',help='IANA time zone for the screening day. Defaults to the runtime local zone for live runs.')
    p.add_argument('--onboarding',type=Path,help='Saved trial upload profile, optionally with a simulated cycle start.')
    p.add_argument('--encounter')
    p.add_argument('--episode')
    a=p.parse_args()
    try:
        profile=validate_onboarding(json.loads(a.onboarding.read_text()),a.study) if a.onboarding else None
        if profile:
            a.timezone=a.timezone or profile['timezone']
        if a.study=='NCT05653388':
            if not a.episode:
                p.error('Supply the indexed cancer --episode for the Michigan adapter.')
            # The legacy engine compares calendar dates and takes a caller-frozen snapshot.
            if a.as_of is not None and re.fullmatch(r'\d{4}-\d{2}-\d{2}', a.as_of):
                day = date.fromisoformat(a.as_of).isoformat()
                if a.timezone:
                    ZoneInfo(a.timezone)
                cycle=test_cycle(profile) if profile else None
                if cycle and day < cycle['onboarded_on']:
                    p.error('The simulated trial configuration was unavailable on that date.')
            else:
                cutoff=screening_cutoff(a.as_of,a.timezone)
                day=instant(cutoff).date().isoformat()
                cycle=test_cycle(profile,cutoff) if profile else None
            legacy=json.loads(subprocess.check_output([sys.executable,str(HERE/'michigan.pyz'),'--bundle',str(a.bundle),'--patient',a.patient,'--episode',a.episode,'--as-of',day,'--trace']))
            criteria={k:{'state':v} for k,v in legacy.get('outcomes',{}).items()}
            for k,v in legacy.get('holds',{}).items():
                criteria[k]={'state':'BINDING_HOLD','reason':v}
            result={**legacy,'screening_date':day,'as_of_source':'run_clock' if a.as_of is None else 'explicit','as_of_precision':'calendar_day',**grouped(criteria)}
            if cycle:
                result.update(mode='simulation',simulated_schedule=cycle)
        else:
            if not a.encounter:
                p.error('Supply the study screening --encounter.')
            result=run(a.study,json.loads(a.bundle.read_text()),a.patient,a.encounter,a.as_of,timezone_name=a.timezone,onboarding=profile)
    except (ValueError, ZoneInfoNotFoundError) as error:
        p.error(str(error))
    print(json.dumps(result,indent=2))
