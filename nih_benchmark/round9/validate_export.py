"""Cross-check the canonical export, FHIR R4 JSON schemas, reference ownership, evidence and local index."""
from collections import Counter
from contextlib import closing
import argparse,base64,csv,json,zipfile
from pathlib import Path
from jsonschema import Draft6Validator
from convert import HERE,rid,load,dump,hashtext
from chart import open_chart,search

def references(obj):
    if isinstance(obj,dict):
        for k,v in obj.items():
            if k=='reference' and isinstance(v,str):yield v
            else:yield from references(v)
    if isinstance(obj,list):
        for x in obj:yield from references(x)

def validate(path):
    with zipfile.ZipFile(HERE/'r4-schema.zip') as z:schema=json.loads(z.read('fhir.schema.json'))
    validators={}
    def schema_check(r):
        kind=r['resourceType']
        if kind not in validators:
            validators[kind]=Draft6Validator({'$ref':'#/definitions/'+kind,'definitions':schema['definitions']})
        validators[kind].validate(r)
    resource_count=0;link_count=0;allids={};patients=0;groups=0
    notes=load(HERE/'notes.json');pins=load(HERE/'note_hashes.json')
    with closing(open_chart(path/'chart.sqlite')) as db:
        for file in sorted((path/'bundles').glob('*.json')):
            b=load(file);items=[e['resource'] for e in b['entry']]
            # Validate entry resources independently, then verify all Bundle/entry fields with
            # the official Bundle schema (its nested ResourceList accepts the full definitions).
            schema_check(b)
            chart={rid(r):r for r in items};case=file.stem
            doc=chart['DocumentReference/'+case+'-note'];subject=doc['subject']['reference']
            patients+=subject.startswith('Patient/');groups+=subject.startswith('Group/')
            assert sorted(rid(r) for r in search(db,subject))==sorted(chart)
            text=base64.b64decode(doc['content'][0]['attachment']['data'],validate=True).decode()
            assert text==notes[case] and hashtext(text)==pins[case]
            for e in b['entry']:
                r=e['resource'];ref=rid(r);assert e['request']=={'method':'PUT','url':ref} and e['fullUrl'].endswith('/'+ref)
                if ref in allids:assert allids[ref]==r and r['resourceType']=='Device'
                else:
                    schema_check(r);resource_count+=1;allids[ref]=r
                for link in references(r):
                    assert link in chart,(ref,link);link_count+=1
                if r['resourceType']=='Provenance':
                    assert r['entity'][0]['what']['reference']==rid(doc)
                    bounds={e['url']:e['valueInteger'] for e in r['entity'][0]['extension']}
                    for e in r['entity'][0]['extension']:
                        if e['url']=='urn:pocketmd:trialgpt:source-sentence':
                            assert 0<=e['valueInteger']<len(text.splitlines())
                    if 'urn:pocketmd:source-char-start' in bounds:
                        assert 0<=bounds['urn:pocketmd:source-char-start']<bounds['urn:pocketmd:source-char-end']<=len(text)
                if r['resourceType'] in {'Condition','Observation','Procedure','MedicationStatement'}:assert r['subject']['reference']==subject
            if subject.startswith('Group/'):assert set(r['resourceType'] for r in items)=={'Device','Group','DocumentReference'}
    nd={rid(r):r for f in (path/'ndjson').glob('*.ndjson') for r in map(json.loads,f.read_text().splitlines())}
    assert nd==allids and len(notes)==patients+groups
    assert len({x['resource'] for x in load(path/'source_links.json')})==sum(r['resourceType']=='Provenance' for r in nd.values())
    out=dict(schema='HL7 FHIR R4 4.0.1 JSON schema',bundles=patients+groups,unique_resources=resource_count,
             within_bundle_reference_occurrences=link_count,source_note_round_trips=len(notes),index_agrees_with_export=True,
             scope='Schema, local references, subject isolation and provenance. No full terminology or implementation-guide certification.')
    dump(path/'validation.json',out);return out
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('export',type=Path);print(validate(p.parse_args().export))
