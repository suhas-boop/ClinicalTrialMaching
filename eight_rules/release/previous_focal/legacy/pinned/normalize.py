"""Apply this release's synthetic site's exact ECOG code mapping, retaining its original coding."""
import argparse
import json
from copy import deepcopy
from pathlib import Path
SOURCE='urn:pocketmd:demo:hospital-lab:v1'
LOCAL='ECOG-PS'
SYSTEM='http://loinc.org'
CODE='89247-1'

def normalize(bundle):
    out=deepcopy(bundle)
    if out.get('resourceType')!='Bundle' or out.get('type')!='collection':raise ValueError('Expected FHIR collection Bundle.')
    audit=[]
    for item in out.get('entry',[]):
        r=item['resource']
        if r.get('resourceType')!='Observation':continue
        codes=r.get('code',{}).get('coding',[])
        if not any(c.get('system')==SOURCE and c.get('code')==LOCAL for c in codes):continue
        if any(c.get('system')==SYSTEM and c.get('code')!=CODE for c in codes):raise ValueError('Conflicting coding for '+r['id'])
        if type(r.get('valueInteger')) is not int or r['valueInteger'] not in range(6):raise ValueError('Expected ECOG integer 0–5.')
        if not any(c.get('system')==SYSTEM and c.get('code')==CODE for c in codes):
            codes.append({'system':SYSTEM,'code':CODE,'display':'ECOG Performance Status score'})
        audit.append({'source':'Observation/'+r['id']+'/_history/'+r['meta']['versionId'],'map':'demo-ecog-v1','from':[SOURCE,LOCAL],'to':[SYSTEM,CODE]})
    return out,audit

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('bundle',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    if a.output.exists():p.error('Choose a new snapshot output path.')
    b,audit=normalize(json.loads(a.bundle.read_text()));a.output.write_text(json.dumps(b,indent=2)+'\n')
    print(json.dumps(audit,indent=2))
