"""Resolve the compiled selectors against one source-linked R9 patient chart."""
from collections import defaultdict
import base64
import hashlib
import math
from clinical_fields import STUDY_TAG
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
    if mode=='field_category' and fields==['valueCodeableConcept']:
        options={c.get('code') for c in resource['valueCodeableConcept'].get('coding',[])
                 if c.get('system')==LOCAL+'/'+selector['local_code']}
        if len(options)==1 and options<=set(selector['answers']):
            return options.pop() in selector['true_values']
    if mode=='field_quantity' and fields==['valueQuantity']:
        q=resource['valueQuantity']
        if ('coding' in selector and tuple(selector['coding']) not in coding_pairs(resource)) or 'comparator' in q:return None
        if (q.get('system'),q.get('code'))!=(UNIT,selector['unit']):return None
        v=q.get('value')
        if type(v) not in (float,int) or not math.isfinite(v) or v<selector['minimum']:return None
        if selector['maximum'] is not None and v>selector['maximum']:return None
        if selector['integer'] and v!=int(v):return None
        return v
    if mode == 'negative_on_affirmation' and fields==['valueBoolean']:
        return False if resource['valueBoolean'] is True else None
    if mode == 'affirmative_boolean' and fields == ['valueBoolean']:
        return True if resource['valueBoolean'] is True else None
    if mode in {'boolean','field_boolean'} and fields==['valueBoolean']:
        return resource['valueBoolean']
    if mode=='affirmation' and fields==['valueString'] and resource['valueString']==selector['phrase']:
        return True
    if mode=='quantity' and fields==['valueQuantity']:
        q=resource['valueQuantity']
        if (tuple(selector['coding']) in coding_pairs(resource) and 'comparator' not in q
                and (q.get('system'),q.get('code'))==(UNIT,selector['unit'])):
            v=q.get('value')
            if type(v) in (int,float) and math.isfinite(v) and v >= 0:
                return v
    return None

class NativeChart:
    def __init__(self, resources, subject, catalog, study=None, *, source_reference=None, document_readers=None):
        self.study=study
        self.catalog=catalog
        self.subject=subject
        records={}
        for r in resources:
            if records.setdefault(rid(r),r)!=r:
                raise ValueError('Conflicting resource identity')
        self.source=source_reference or 'DocumentReference/'+subject.split('/')[1]+'-note'
        if subject not in records or self.source not in records:
            raise ValueError('Unknown subject or missing source document')
        doc=records[self.source]
        if doc['resourceType']!='DocumentReference' or doc.get('status')!='current' or doc.get('subject',{}).get('reference')!=subject:
            raise ValueError('Wrong source for patient')
        raw=base64.b64decode(doc['content'][0]['attachment']['data'],validate=True)
        self.hash=hashlib.sha256(raw).hexdigest()
        if not any(i.get('system')=='urn:pocketmd:sha256' and i.get('value')==self.hash for i in doc['identifier']):
            raise ValueError('Invalid source digest')
        source_text=raw.decode()
        nlines=len(source_text.splitlines())
        starts=[0]
        for line in source_text.splitlines(keepends=True):starts.append(starts[-1]+len(line))
        self.document_readers = document_readers or {}
        self.refs = {ref:[span["line"]] for reader in self.document_readers.values() for ref,span in reader.spans.items()}
        self.index=defaultdict(list)
        by_target=defaultdict(list)
        for p in resources:
            if p['resourceType']!='Provenance' or p.get('modifierExtension') or p.get('implicitRules'):
                continue
            agent=p.get('agent',[])
            producer=next((d for d in ('Device/pocketmd-r9','Device/pocketmd-prose-r12')
                           if d in records and agent==[{'who':{'reference':d}}]),None)
            if not producer:continue
            entities=p.get('entity',[]);targets=p.get('target',[])
            if len(entities)!=1 or len(targets)!=1:continue
            e=entities[0]
            if e.get('role')!='source' or e.get('what',{}).get('reference')!=self.source:continue
            ids=[x.get('valueInteger') for x in e.get('extension',[]) if x.get('url')==LINE]
            if not ids or any(type(i)!=int or not 0<=i<nlines for i in ids):continue
            if producer=='Device/pocketmd-prose-r12':
                ext=e.get('extension',[])
                bounds=[[a.get('valueInteger') for a in ext if a.get('url')=='urn:pocketmd:source-char-'+side] for side in ('start','end')]
                if any(len(v)!=len(ids) or any(type(n)!=int for n in v) for v in bounds):continue
                if any(not starts[i]<=lo<hi<=starts[i+1] for i,lo,hi in zip(ids,*bounds)):continue
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
                self.index[(r['resourceType'],system,code)].append((r,target,contexts[0]))
                if system==LOCAL:
                    self.index[(r['resourceType'],code)].append((r,target,contexts[0]))

    def qualitative_context(self, label):
        """Return source-linked observations that leave a requested fact unresolved."""
        sign = {"heart_rate": "tachycardia", "respiratory_rate": "tachypnea"}.get(label)
        consent_labels = {"refused_written_consent", "consent_refused", "consent_absent",
                          "unable_to_provide_written_consent"}
        stroke_context = label == "neurologic_symptoms_nonvascular_origin_after_ct_or_mri"
        if sign:
            local_code = "exam-sign-" + sign
        elif stroke_context:
            local_code = "documented-stroke-episode-with-linked-brain-imaging"
        elif label in consent_labels:
            local_code = "expressed-future-consent-intent"
        else:
            return []
        matches = []
        for r, target, scope in self.index.get(("Observation", local_code), []):
            study_tags = [e.get("valueString") for e in r.get("extension", [])
                          if e.get("url") == STUDY_TAG]
            if study_tags and (sign or stroke_context or study_tags != [self.study]):
                continue
            value = value_for(r, {"read": "boolean", "context": "note abstraction"}, scope)
            if value is True:
                entry = dict(resource=target, source_lines=self.refs[target])
                if sign:
                    entry["sign"] = sign
                elif stroke_context:
                    entry.update(finding="Documented stroke episode with linked brain CT or MRI.",
                                 missing="Post-imaging attribution of the presenting neurologic symptoms.")
                else:
                    entry.update(finding="intent to provide informed consent",
                                 study_scope="matching study" if study_tags else "unspecified")
                matches.append(entry)
        return matches

    def read(self,spec):
        definition=self.catalog.get(contract(spec))
        if not definition or definition['spec']!=spec:
            return None,'BINDING_HOLD',[],'Rule fact has no exact shared contract.'
        if spec['role']!='record':
            return None,ROLE_MISSING[spec['role']],[],spec['scope']
        if not definition['native']:
            return None,'BINDING_HOLD',[],'Implement a patient-chart mapping for '+spec['scope']+'.'
        selectors = definition['native']
        if len(selectors) == 1 and selectors[0].get('resource') == 'DocumentReference':
            selector = selectors[0]
            reader = self.document_readers.get(selector['read'])
            if reader is None or selector['local_code'] != spec['label'] or reader.digest != self.hash:
                return None,'BINDING_HOLD',[],'Verified source reader unavailable for '+spec['scope']+'.'
            return reader.read(spec)
        found=[]
        for s in selectors:
            standard_quantity = s.get('coding') and s['read'] in ('quantity', 'field_quantity')
            lookup = (s['resource'], *s['coding']) if standard_quantity else (s['resource'], s['local_code'])
            for r,ref,scope in self.index.get(lookup,[]):
                if standard_quantity:
                    pairs = coding_pairs(r)
                    standard_system, expected_code = s['coding']
                    if any(system == standard_system and code != expected_code for system, code in pairs):
                        continue
                    if any(system == LOCAL and code != s['local_code'] for system, code in pairs):
                        continue
                study_tags=[v.get('valueString') for v in r.get('extension',[]) if v.get('url')==STUDY_TAG]
                if study_tags and study_tags!=[self.study]:continue
                if s.get('study_scoped') and (not self.study or study_tags!=[self.study]):continue
                value=value_for(r,s,scope)
                if 'whole_age_boundary' in s:
                    if (type(value) not in (int, float) or not math.isfinite(value)
                            or value < 0 or value != int(value)):
                        continue
                    boundary, below, at_or_above = s['whole_age_boundary']
                    value = below if value < boundary else at_or_above
                if value is not None and typed(value,spec):
                    found.append((value,ref))
        refs=sorted({ref for _,ref in found})
        if not found:
            return None,'MISSING_DATA',[],'Obtain source-linked '+spec['scope']+'.'
        if len({v for v,_ in found})!=1:
            return None,'MISSING_DATA',refs,'Reconcile conflicting '+spec['scope']+'.'
        return found[0][0],None,refs,'Source-linked '+spec['scope']+'.'
