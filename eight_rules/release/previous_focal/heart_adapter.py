"""Native LOINC heart-rate binding for SOTIO Amendment 1, exclusion 17.

Accepts an original FHIR R4 Observation with final measured pulse, mapped study encounter,
versioned clinician source and trusted performer. Two site-onboarded event documents identify
main consent signing and C1D1 (actual or explicitly planned). Their context.period.start carries
the event instant; date is the separate time the source record became available. References in
context["heart_rate_anchors"] must identify current exact versions, scoped to this participant,
encounter, source authority and protocol. The mapping of those event types is research-only.
"""
import math
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from normalized import HASH, SOURCE, STUDY, UCUM, contract, instant, ref, relative, tag

LOINC = 'http://loinc.org'
PULSE = '8867-4'
EVENT = 'urn:pocketmd:research:106S01:dated-event'
GOOD = {'final','amended','corrected'}
ERROR = 'MISSING_DATA'

def codes(resource):
    if not isinstance(resource,dict) or not isinstance(resource.get('coding'),list): return set()
    return {(c.get('system'),c.get('code')) for c in resource['coding'] if isinstance(c,dict) and isinstance(c.get('system'),str) and isinstance(c.get('code'),str)}

def identical_subject(obj,target):
    return isinstance(obj.get('subject'),dict) and obj['subject'].get('reference')==target

def valid_source(doc, patient, encounter, cutoff, trusted):
    return (doc.get('resourceType')=='DocumentReference' and doc.get('status')=='current'
            and identical_subject(doc,patient) and tag(doc,SOURCE,HASH)
            and not doc.get('modifierExtension') and not doc.get('implicitRules')
            and instant(doc['date'])<=instant(doc['meta']['lastUpdated'])<=cutoff
            and any(item.get('attachment',{}).get('contentType') and
                    any(item['attachment'].get(k) for k in ('url','data'))
                    for item in doc.get('content',[]))
            and (not doc.get('context',{}).get('encounter')
                 or {e['reference'] for e in doc['context']['encounter']}=={encounter})
            and bool({x['reference'] for x in doc['author']} & trusted))

def read_anchor(name, pointers, latest, patient, encounter, cutoff, trusted, allowed):
    key=pointers[name]
    if not isinstance(key,str) or '/_history/' not in key: raise ValueError()
    doc=latest[key.split('/_history/')[0]]
    if ref(doc)!=key or not valid_source(doc,patient,encounter,cutoff,trusted):
        raise ValueError()
    if {e['reference'] for e in doc['context'].get('encounter',[])}!={encounter}: raise ValueError()
    types={code for sys,code in codes(doc['type']) if sys==EVENT}
    if len(types)!=1 or not types<=allowed: raise ValueError()
    kind=types.pop()
    time=instant(doc['context']['period']['start'])
    if kind in {'main-icf-signed','c1d1-actual'} and (time>instant(doc['date']) or time>cutoff): raise ValueError()
    return time,kind,key

def derive(rules, bundle, context):
    """Return keyed native binding results; absence of same-patient eligible resource type returns {}."""
    rule=rules.get('E17') or rules.get('106S01-E17')
    if not rule:return {}
    spec=rule['facts']['heart_rate']
    key=contract(spec)
    patient=relative(context['patient'],'Patient'); encounter=relative(context['encounter'],'Encounter')
    available=lambda reason,refs=(): {key:(None,ERROR,sorted(set(refs)),reason)}
    if context.get('study')!='106S01' or context.get('protocol_sha256')!=HASH:return {}
    if bundle.get('resourceType')!='Bundle' or bundle.get('type')!='collection':return {}
    raw=[e['resource'] for e in bundle.get('entry',[]) if isinstance(e,dict) and isinstance(e.get('resource'),dict)]
    def candidate(r):
        return (r.get('resourceType')=='Observation' and identical_subject(r,patient)
                and isinstance(r.get('encounter'),dict) and r['encounter'].get('reference')==encounter
                and (LOINC,PULSE) in codes(r.get('code',{})))
    if not any(candidate(r) for r in raw):return {}
    if key not in context.get('enabled_contracts',[]):return {key:(None,'BINDING_HOLD',[],'Enable the validated screening pulse binding.')}
    try:
        cutoff=instant(context['as_of']); zone=ZoneInfo(context['site_zone'])
        latest={}; stamps={}; versions={}
        # Resolve every version of a relevant logical ID, including retractions, while ignoring
        # unrelated chart resources that did not contribute to this binding.
        pointers=context.get('heart_rate_anchors',{})
        relevant={patient,encounter}
        for target in pointers.values():
            if isinstance(target,str):relevant.add(target.split('/_history/')[0])
        for r in raw:
            if candidate(r):
                relevant.add('Observation/'+r['id'])
                for link in r.get('derivedFrom',[]):
                    relevant.add(link['reference'].split('/_history/')[0])
        for r in raw:
            if not r.get('resourceType') or not isinstance(r.get('id'),str) or r['resourceType']+'/'+r['id'] not in relevant:continue
            # A competing version with unknown metadata cannot safely be used at a historical cutoff.
            if not isinstance(r.get('id'),str) or not r['id'] or not isinstance(r.get('meta',{}).get('versionId'),str):raise ValueError()
            if not r['meta']['versionId']:raise ValueError()
            stamp=instant(r['meta']['lastUpdated'])
            if stamp>cutoff:continue
            version=ref(r);logical=version.split('/_history/')[0]
            if version in versions and versions[version]!=r:raise ValueError()
            versions[version]=r
            if logical not in latest or stamp>stamps[logical]:latest[logical]=r;stamps[logical]=stamp
            elif stamp==stamps[logical] and latest[logical]!=r:raise ValueError()
        if patient not in latest or encounter not in latest:return {}
        enc=latest[encounter]
        if (enc.get('status') not in {'in-progress','finished'} or not identical_subject(enc,patient)
                or not tag(enc,STUDY,'106S01|'+HASH+'|screening')):return {}
        pulse=[r for r in latest.values() if candidate(r) and r.get('status') not in ('cancelled','entered-in-error')]
        if not pulse:return {}
        role=context['trusted_roles']
        clinicians=set(role.get('record',[]))
        event_writers=clinicians|set(role.get('site',[]))
        consent,_,consent_ref=read_anchor('main_consent',context['heart_rate_anchors'],latest,patient,encounter,cutoff,event_writers,{'main-icf-signed'})
        cycle,cycle_kind,cycle_ref=read_anchor('cycle1',context['heart_rate_anchors'],latest,patient,encounter,cutoff,event_writers,{'c1d1-actual','c1d1-planned'})
        day=cycle.astimezone(zone).date()
        if not 1<=(day-consent.astimezone(zone).date()).days<=21:raise ValueError()
        refs=[ref(enc),ref(latest[patient]),consent_ref,cycle_ref]; readings=[]
        for obs in pulse:
            measured=instant(obs['effectiveDateTime']); issued=instant(obs['issued'])
            if measured<consent or not 1<=(day-measured.astimezone(zone).date()).days<=21 or issued>cutoff or measured>cutoff:
                continue
            if (obs.get('status') not in GOOD or obs.get('modifierExtension') or obs.get('implicitRules')
                    or measured>issued or issued>stamps['Observation/'+obs['id']] or obs.get('dataAbsentReason')
                    or {c for sys,c in codes(obs['code']) if sys==LOINC}!={PULSE}
                    or {k for k in obs if k.startswith('effective')}!={'effectiveDateTime'}
                    or {k for k in obs if k.startswith('value')}!={'valueQuantity'}):raise ValueError()
            q=obs['valueQuantity']; value=q['value']
            if (q.get('system')!=UCUM or q.get('code')!='/min' or q.get('comparator')
                    or type(value) not in (float,int) or not math.isfinite(value) or value<=0):raise ValueError()
            performers={x['reference'] for x in obs['performer']} & clinicians
            if not performers or not obs['derivedFrom']:raise ValueError()
            for link in obs['derivedFrom']:
                dr=link['reference']; doc=versions[dr]
                if latest[dr.split('/_history/')[0]]!=doc or not valid_source(doc,patient,encounter,cutoff,performers):raise ValueError()
                refs.append(dr)
            readings.append(value); refs.append(ref(obs))
        if not readings:return available('Obtain a final heart rate within the signed study screening interval.')
        if len(set(readings))!=1:return available('Reconcile conflicting native screening pulse values.',refs)
        label='planned' if cycle_kind=='c1d1-planned' else 'actual'
        return {key:(readings[0],None,sorted(set(refs)),f'Versioned screening pulse from LOINC {PULSE} in UCUM /min, using {label} C1D1.')}
    except (KeyError,ValueError,TypeError,IndexError,OverflowError,AttributeError,ZoneInfoNotFoundError):
        return available('Verify the native screening pulse, its source and performer, version history, signed consent and study-specific C1D1.')
