"""Attach a local, versioned ClinicalTrials.gov record to a rule authoring request."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re

def packet(study,criterion,raw):
    records=json.loads(raw)
    section=records['protocolSection']
    if not re.fullmatch(r'NCT\d{8}',study) or section['identificationModule']['nctId']!=study:
        raise ValueError('Trial identifier mismatch.')
    ctx=section.get('eligibilityModule',{})
    parts={'eligibilityCriteria':ctx.get('eligibilityCriteria',''),**{k:section.get('descriptionModule',{}).get(k,'') for k in ('briefSummary','detailedDescription')}}
    norm=lambda s:' '.join(s.casefold().split())
    return dict(study=study,registry_sha256=sha256(raw).hexdigest(),registry_url='https://clinicaltrials.gov/study/'+study,
        last_update=section.get('statusModule',{}).get('lastUpdatePostDateStruct',{}).get('date'),
        criterion_in_eligibility_text=bool(criterion.strip()) and norm(criterion) in norm(parts['eligibilityCriteria']),
        minimum_age=ctx.get('minimumAge'),maximum_age=ctx.get('maximumAge'),sections=parts,
        authority='Current public registry context; confirm the governing protocol version before changing a released rule.')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('study');p.add_argument('record',type=Path);p.add_argument('criterion')
    args=p.parse_args()
    print(json.dumps(packet(args.study,args.criterion,args.record.read_bytes()),indent=2))
