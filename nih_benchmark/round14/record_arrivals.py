"""Controlled replay of independently sourced reports at one known benchmark encounter.

The caller assigns the actual encounter from its trusted intake context. Replay
uses a synthetic encounter and synthetic supplemental records. No label or
patient endpoint from this experiment enters the original benchmark score.
"""
import base64
import json
import re
import sys
from hashlib import sha256
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'round12'))
from intake import plain_chart, ref, rid
from screen import R11, verify, read_json
from native import NativeChart
from evidence_review import screen_snapshot
from run import fingerprint

def receive(patient, encounter_id, document_id, text, timestamp):
    bundle, _ = plain_chart(patient, text, timestamp, document_id=document_id)
    items = [e['resource'] for e in bundle['entry']]
    subject = ref('Patient/' + patient)
    visit = 'Encounter/' + encounter_id
    encounter = dict(resourceType='Encounter', id=encounter_id, subject=subject,
                     status='finished', **{'class':{'system':'http://terminology.hl7.org/CodeSystem/v3-ActCode','code':'EMER'}})
    doc = next(r for r in items if r['resourceType']=='DocumentReference')
    doc['context'] = {'encounter':[ref(visit)]}
    return [encounter, *items]


def verified_intake_facts(records, document, subject, visit, view):
    """Reproduce the supplied values and exact source spans from the linked original text."""
    content=document.get('content',[])
    if (len(content)!=1 or content[0].get('attachment',{}).get('contentType')!='text/plain'
            or document.get('docStatus')=='entered-in-error' or document.get('modifierExtension') or document.get('implicitRules')):
        raise ValueError('Expected one current plain-text source with supported semantics')
    raw=base64.b64decode(content[0]['attachment']['data'],validate=True).decode()
    generated,_=plain_chart(subject.removeprefix('Patient/'),raw,'2000-01-01T00:00:00Z',document_id=document['id'])
    def target_payload(record):
        return {k:v for k,v in record.items() if k not in ('id','meta','encounter')}
    def proof(record, prov):
        return fingerprint([target_payload(record),prov['entity'],prov['agent']])
    extracted={rid(e['resource']):e['resource'] for e in generated['entry']}
    supported={proof(extracted[p['target'][0]['reference']],p) for p in extracted.values() if p['resourceType']=='Provenance'}
    checked=set()
    for prov in records.values():
        if prov['resourceType']!='Provenance' or len(prov.get('target',[]))!=1:
            continue
        target=prov['target'][0].get('reference')
        if target not in view.refs or len(prov.get('entity',[]))!=1:
            continue
        if prov['entity'][0].get('what',{}).get('reference')!=rid(document):
            continue
        r=records[target]
        if 'encounter' in r and r['encounter'].get('reference')!=visit:
            raise ValueError('Source observation is linked to a different encounter: '+target)
        if proof(r,prov) not in supported:
            raise ValueError('Value or provenance cannot be reproduced from the source document: '+target)
        checked.add(target)
    if checked!=set(view.refs):
        raise ValueError('Patient evidence lacks reproducible source provenance')


def join_views(items, subject, visit, catalog, study, *, verify_intake=False):
    # Conflicting payloads must not share an unversioned resource identity.
    index = {}
    for resource in items:
        key = rid(resource)
        previous = index.setdefault(key, resource)
        if previous == resource:
            continue
        # A transport retry may run the same extractor later. The first receipt
        # still establishes provenance for identical content and source spans.
        if resource['resourceType'] == 'Provenance':
            if ({k:v for k,v in previous.items() if k!='recorded'} ==
                    {k:v for k,v in resource.items() if k!='recorded'}):
                recorded = lambda r: datetime.fromisoformat(r['recorded'].replace('Z', '+00:00'))
                index[key] = min((previous,resource), key=recorded)
                continue
        raise ValueError('Conflicting resource identity: '+key)
    if not visit.startswith('Encounter/') or index.get(visit,{}).get('subject') != ref(subject):
        raise ValueError('Encounter must identify the requested patient')
    encounter=index[visit]
    if verify_intake and (encounter.get('status') in {'entered-in-error','cancelled'}
                          or encounter.get('modifierExtension') or encounter.get('implicitRules')):
        raise ValueError('Encounter is invalid or has unsupported semantics')
    sources = sorted(key for key,r in index.items() if r['resourceType']=='DocumentReference'
                     and r.get('subject')==ref(subject) and r.get('status')=='current'
                     and r.get('context',{}).get('encounter')==[ref(visit)])
    if not sources:
        raise ValueError('No linked source documents for the patient and encounter')
    # Each view independently verifies its raw digest, source roles, subject,
    # producer and exact bounded provenance. The shared reader then resolves
    # values across the resulting indices (including discrepant quantities).
    combined = None
    docs, locations = {}, {}
    for source in sources:
        view = NativeChart(list(index.values()),subject,catalog,study,source_reference=source)
        if verify_intake:
            verified_intake_facts(index,index[source],subject,visit,view)
        docs[source] = view.hash
        for target,lines in view.refs.items():
            if target in locations:
                raise ValueError('Ambiguous source '+target)
            locations[target] = dict(document=source, sha256=view.hash, lines=lines)
        if combined is None:
            combined = view
        else:
            for key, values in view.index.items():
                combined.index[key].extend(values)
            combined.refs.update(view.refs)
    combined.hash = fingerprint(dict(patient=subject, encounter=visit, sources=docs))
    return combined, locations


def evaluate(items, patient, encounter_id, pack, study, criteria, *, verify_intake=False):
    rules = {k:pack['rules'][k] for k in criteria}
    if any(entry['source']['trial_id'] != study for entry in rules.values()):
        raise ValueError('Rule belongs to another study')
    subject='Patient/'+patient
    visit='Encounter/'+encounter_id
    snapshot, locations=join_views(items,subject,visit,pack['contracts'],study,verify_intake=verify_intake)
    ctx=dict(patient=subject,episode='benchmark presentation',encounter=visit,as_of=snapshot.hash,
             source_scope='individual',source_sha256=snapshot.hash)
    version=fingerprint({k:{name:e[name] for name in ('rule','source')} for k,e in pack['rules'].items()
                         if e['source']['trial_id']==study})
    trace=screen_snapshot({k:entry['rule'] for k,entry in rules.items()},snapshot,ctx,study,version)
    for criterion in trace['criteria'].values():
        cited={key for fact in criterion['facts'].values() for key in fact['evidence']}
        criterion['locations']={key:locations[key] for key in sorted(cited)}
    trace.update(snapshot_sha256=snapshot.hash,catalog_sha256=pack['sha256'])
    return trace


def screen_encounter(items, subject, visit, pack, study, criterion=None):
    patt=r'[A-Za-z0-9.-]{1,64}'
    if not re.fullmatch('Patient/'+patt,subject) or not re.fullmatch('Encounter/'+patt,visit):
        raise ValueError('Supply literal Patient/id and Encounter/id references')
    ids=[k for k,v in pack['rules'].items() if v['source']['trial_id']==study]
    if not ids or (criterion is not None and criterion not in ids):
        raise ValueError('Unknown study or criterion')
    return evaluate(items,subject.split('/')[1],visit.split('/')[1],pack,study,
                    [criterion] if criterion is not None else ids,verify_intake=True)


def experiment():
    pack=verify(read_json(R11/'compiled.json'))
    pid='sigir-201411'
    src=read_json(R11.parent/'round9/notes.json')[pid]
    encounter='demo-index-'+pid
    study=pack['rules']['186']['source']['trial_id']
    timestamp='2026-01-01T00:00:00Z'
    index=receive(pid,encounter,'demo-original-note',src,timestamp)
    def supplemental(name,text,visit=encounter,patient=pid):
        return receive(patient,visit,name,text,'2026-01-01T00:30:00Z')
    at=supplemental('demo-vitals-at','Heart rate: 90 bpm.\nRespiratory rate: 20/min.')
    late=receive(pid,encounter,'demo-vitals-at','Heart rate: 90 bpm.\nRespiratory rate: 20/min.',
                 '2026-01-02T05:00:00Z')
    below=supplemental('demo-vitals-below','Heart rate: 89 bpm.\nRespiratory rate: 19/min.')
    wrong=supplemental('demo-other-visit','Heart rate: 135 bpm.\nRespiratory rate: 28/min.',visit='demo-other')
    other=supplemental('demo-other-patient','Heart rate: 140 bpm.',visit='demo-other-pt-visit',patient='demo-other-patient')
    abg=supplemental('demo-abg','Arterial blood gas showed PaCO2 of 40 mmHg.')
    breathing=supplemental('demo-resp','The patient is breathing spontaneously without mechanical ventilation.')
    scenarios=[
        ('original', index, ['MISSING_DATA','MISSING_DATA']),
        ('at_boundaries',index+at,['MET','MET']),
        ('below',index+below,['NOT_MET','MISSING_DATA']),
        ('complete_negative',index+below+abg+breathing,['NOT_MET','NOT_MET']),
        ('redelivery', index+at+late,['MET','MET']),
        ('conflict',index+at+below,['MISSING_DATA','MISSING_DATA']),
        ('wrong_encounter',index+wrong,['MISSING_DATA','MISSING_DATA']),
        ('wrong_patient',index+other,['MISSING_DATA','MISSING_DATA'])]
    result={}
    for name,items,expected in scenarios:
        trace=evaluate(items,pid,encounter,pack,study,['186','187'])
        actual=[trace['criteria'][k]['state'] for k in ('186','187')]
        assert actual==expected,(name, actual, expected)
        result[name]=trace
    assert result['redelivery']==result['at_boundaries']
    assert result['wrong_encounter']==result['wrong_patient']==result['original']
    for k,line in [('186',0),('187',1)]:
        positive=result['at_boundaries']['criteria'][k]
        assert len(positive['evidence'])==1
        point=positive['locations'][positive['evidence'][0]]
        assert point['document']=='DocumentReference/demo-vitals-at' and point['lines']==[line]
    assert len(result['complete_negative']['criteria']['187']['locations'])==3
    for received, message in [
        (index+at+supplemental('demo-vitals-at','Heart rate: 99 bpm.'), 'Conflicting resource identity'),
        (index+[dict(r, identifier=[]) if r['resourceType']=='DocumentReference' else r for r in at],
         'Invalid source digest')]:
        try:
            evaluate(received,pid,encounter,pack,study,['186','187'])
        except ValueError as exc:
            assert message in str(exc), (message,str(exc))
        else:
            raise AssertionError('Expected rejection: '+message)
    return dict(controls=['identity collision rejected','unverifiable source digest rejected'],
                experiment='Synthetic supplemental documents on a frozen vignette; excluded from benchmark counts',
                subject=pid,study=study,original_note_sha256=sha256(src.encode()).hexdigest(),scenarios=result)

if __name__=='__main__':
    run=experiment()
    if len(sys.argv)>1:
        Path(sys.argv[1]).write_text(json.dumps(run,indent=2)+'\n')
    for name,trace in run['scenarios'].items():
        print(name,{k:v['state'] for k,v in trace['criteria'].items()})
