"""Resolve the compiled selectors against one source-linked R9 patient chart."""
from collections import defaultdict
import base64
import hashlib
from catalog import LOCAL, contract
from bindings import ROLE_MISSING
from convert import LINE, SCOPE, UNIT, rid
from rules_engine import typed

def coding_pairs(resource):
    return {(c.get('system'),c.get('code')) for c in resource.get('code',{}).get('coding',[])}

def value_for(resource, selector, scope):
    mode=selector['read']
    if mode=='historical_condition':
        if (scope or '').split(';')[0] != selector['context']:
            return None
        verification = resource.get('verificationStatus')
        if verification and ('http://terminology.hl7.org/CodeSystem/condition-ver-status','confirmed') not in {
                (c.get('system'),c.get('code')) for c in verification.get('coding',[])}:
            return None
        return True
    if scope!=selector['context'] or resource.get('status')!='final':
        return None
    fields=[k for k in resource if k.startswith('value')]
    if resource.get('dataAbsentReason') or len(fields)!=1:
        return None
    if mode=='boolean' and fields==['valueBoolean']:
        return resource['valueBoolean']
    if mode=='affirmation' and fields==['valueString'] and resource['valueString']==selector['phrase']:
        return True
    if mode=='quantity' and fields==['valueQuantity']:
        q=resource['valueQuantity']
        if (tuple(selector['coding']) in coding_pairs(resource) and 'comparator' not in q
                and (q.get('system'),q.get('code'))==(UNIT,selector['unit'])):
            return q.get('value')
    return None

class NativeChart:
    def __init__(self, resources, subject, catalog):
        self.catalog=catalog
        self.subject=subject
        records={}
        for r in resources:
            if records.setdefault(rid(r),r)!=r:
                raise ValueError('Conflicting resource identity')
        self.source='DocumentReference/'+subject.split('/')[1]+'-note'
        if subject not in records or self.source not in records:
            raise ValueError('Unknown subject or missing source document')
        doc=records[self.source]
        if doc.get('status')!='current' or doc.get('subject',{}).get('reference')!=subject:
            raise ValueError('Wrong source for patient')
        raw=base64.b64decode(doc['content'][0]['attachment']['data'],validate=True)
        self.hash=hashlib.sha256(raw).hexdigest()
        if not any(i.get('system')=='urn:pocketmd:sha256' and i.get('value')==self.hash for i in doc['identifier']):
            raise ValueError('Invalid source digest')
        nlines=len(raw.decode().splitlines())
        self.refs={}
        self.index=defaultdict(list)
        by_target=defaultdict(list)
        for p in resources:
            if p['resourceType']!='Provenance' or p.get('modifierExtension') or p.get('implicitRules'):
                continue
            if p.get('agent')!=[{'who':{'reference':'Device/pocketmd-r9'}}] or 'Device/pocketmd-r9' not in records:
                continue
            entities=p.get('entity',[]);targets=p.get('target',[])
            if len(entities)!=1 or len(targets)!=1:continue
            e=entities[0]
            if e.get('role')!='source' or e.get('what',{}).get('reference')!=self.source:continue
            ids=[x.get('valueInteger') for x in e.get('extension',[]) if x.get('url')==LINE]
            if not ids or any(type(i)!=int or not 0<=i<nlines for i in ids):continue
            by_target[targets[0].get('reference')].append(ids)
        for target,spans in by_target.items():
            r=records.get(target,{})
            if r.get('subject',{}).get('reference')!=subject or r.get('modifierExtension') or r.get('implicitRules'):
                continue
            if r['resourceType']=='Observation' and r.get('derivedFrom')!=[{'reference':self.source}]:continue
            if r['resourceType']=='Condition' and r.get('evidence')!=[{'detail':[{'reference':self.source}]}]:continue
            contexts=[x.get('valueString') for x in r.get('extension',[]) if x.get('url')==SCOPE]
            if len(contexts)!=1:continue
            self.refs[target]=sorted({i for ids in spans for i in ids})
            for system,code in coding_pairs(r):
                if system==LOCAL:
                    self.index[(r['resourceType'],code)].append((r,target,contexts[0]))

    def read(self,spec):
        definition=self.catalog.get(contract(spec))
        if not definition or definition['spec']!=spec:
            return None,'BINDING_HOLD',[],'Rule fact has no exact shared contract.'
        if spec['role']!='record':
            return None,ROLE_MISSING[spec['role']],[],spec['scope']
        if not definition['native']:
            return None,'BINDING_HOLD',[],'Implement a patient-chart mapping for '+spec['scope']+'.'
        found=[]
        for s in definition['native']:
            for r,ref,scope in self.index.get((s['resource'],s['local_code']),[]):
                value=value_for(r,s,scope)
                if value is not None and typed(value,spec):
                    found.append((value,ref))
        refs=sorted({ref for _,ref in found})
        if not found:
            return None,'MISSING_DATA',[],'Obtain source-linked '+spec['scope']+'.'
        if len({v for v,_ in found})!=1:
            return None,'MISSING_DATA',refs,'Reconcile conflicting '+spec['scope']+'.'
        return found[0][0],None,refs,'Source-linked '+spec['scope']+'.'
