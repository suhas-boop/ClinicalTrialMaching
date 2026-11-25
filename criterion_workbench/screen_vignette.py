"""Research-only adapter for numbered public vignettes; the encounter is synthetic."""
import argparse
import base64
from hashlib import sha256
import json
from pathlib import Path

from narrative_evidence import extract, supports
from evidence_review import screen
from bindings import contract, make_packet, ref
from rules_engine import validate, typed

def evaluate_vignette(rule, patient, study, criterion_text, note, assisted=None, use_reader=True):
    validate(rule)
    scope=extract(note)
    note_hash=sha256(note.encode()).hexdigest()
    if use_reader and scope['scope']=='multiple_subjects':
        required='Identify a single index patient before evaluating patient-specific criteria.'
        request_id=sha256(json.dumps([patient,note_hash,required]).encode()).hexdigest()
        return {'state':'SOURCE_SCOPE_HOLD','reason':required,'sentences':[],'partial_sentences':[],
                'source':note_hash,'extracted':[], 'requests':[{'id':request_id,'route':'identify_subject','request':required}]}
    lines={int(n):s for n,s in (line.split('. ',1) for line in note.strip().splitlines())}
    known={k:(v[0],list(v[1])) for k,v in (assisted or {}).items() if k in rule['facts']}
    extracted=[]
    if use_reader:
        for k,f in scope['facts'].items():
            if k not in rule['facts'] or not supports(k,rule['facts'][k]):continue
            if k in known and known[k][0]!=f['value']:
                raise ValueError('Source and supplied abstraction conflict. Reconcile before evaluating.')
            known[k]=(f['value'],f['sentences']);extracted.append(k)
    for k,(value,ids) in known.items():
        if not typed(value,rule['facts'][k]) or rule['facts'][k]['role']!='record' or not ids or any(i not in lines for i in ids):
            raise ValueError('Invalid or unattributed narrative observation.')
    version=sha256(json.dumps([study,criterion_text,rule],sort_keys=True).encode()).hexdigest()
    pack=make_packet({'criterion':rule},{'criterion':{k:v[0] for k,v in known.items()}},study,version,patient=patient)
    index={}
    for obj in (e['resource'] for e in pack['bundle']['entry']):
        if obj['resourceType']!='DocumentReference':continue
        k=next(k for k in known if obj['id']=='src-'+contract(rule['facts'][k]))
        ids=known[k][1];index[ref(obj)]=ids
        obj['content'][0]['attachment'].update(title=f'{patient} {note_hash[:12]} sentences {ids}',
            data=base64.b64encode('\n'.join(lines[i] for i in ids).encode()).decode())
    out=screen({'criterion':rule},pack,study,version)
    verdict=out['criteria']['criterion']
    def ids(refs):return sorted({i for rid in refs for i in index.get(rid,[])})
    return {'state':verdict['state'],'reason':verdict['reason'],'sentences':ids(verdict['evidence']),
            'partial_sentences':ids(verdict['partial_evidence']),'extracted':extracted,'source':note_hash,'requests':out['requests']}

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input',type=Path,help='JSON containing rule, patient, study, criterion_text and note.')
    print(json.dumps(evaluate_vignette(**json.loads(ap.parse_args().input.read_text())),indent=2))
