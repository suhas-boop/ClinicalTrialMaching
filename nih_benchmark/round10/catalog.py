"""Compile source-reviewed rules and patient selectors into one versioned artifact."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
R9 = HERE.parent / 'round9'
sys.path.insert(0, str(R9))
from convert import LOCAL, LOINC, MEASURES
from author_rules import build, fact
from bindings import contract, FACTS
from concept_reader import CURRENT, HISTORY
from run import fingerprint

def selector(resource, key, context, read, **extra):
    return dict(resource=resource, local_code=key, context=context, read=read, **extra)

def reviewed_native():
    # Reuse the intake vocabulary for explicit, scoped, positive or negative assertions.
    keys = set(CURRENT) | set(HISTORY) | {
        'skin_condition', 'active_treatment_of_any_form_not_considered', 'hospital_admission',
        'pregnant', 'male_or_female', 'woman'}
    mappings = {contract(fact(k)): [selector('Observation', k, 'note abstraction', 'boolean')] for k in keys}
    for key, local, unit, context in [
        ('age_years','age-at-presentation','a','age at vignette presentation'),
        ('heart_rate','heart_rate','/min','presentation'),
        ('respiratory_rate','respiratory_rate','/min','presentation'),
        ('gcs','gcs','1','presentation'),
        ('serum_creatinine_mg_dl','serum_creatinine_mg_dl','mg/dL','presentation')]:
        mappings[contract(fact(key,'number',unit))] = [
            selector('Observation',local,context,'quantity',coding=[LOINC,MEASURES[local][0]],unit=unit)]
    mappings[contract(fact('history_of_mi'))].append(
        selector('Condition','myocardial-infarction','history','historical_condition'))
    mappings[contract(fact('respiratory_distress'))].append(
        selector('Observation','respiratory_distress','current','affirmation',phrase='in respiratory distress'))
    return mappings

def compile_pack():
    rules = build()
    profiles = reviewed_native()
    catalog = {}
    for entry in rules.values():
        entry['bindings'] = {}
        for key, spec in entry['rule']['facts'].items():
            if key != spec['label']:
                raise ValueError('Conflicting fact name')
            cid = contract(spec)
            definition = dict(spec=spec, normalized_system=FACTS, native=profiles.get(cid,[]))
            if catalog.setdefault(cid,definition) != definition:
                raise ValueError('Conflicting evidence contract')
            entry['bindings'][key] = cid
    pack = dict(format_version=1, rules=rules, contracts=catalog)
    return dict(**pack, sha256=fingerprint(pack))

def verify(pack):
    payload = {k:v for k,v in pack.items() if k!='sha256'}
    if payload.get('format_version') != 1 or fingerprint(payload) != pack.get('sha256'):
        raise ValueError('Shared catalog fingerprint mismatch')
    for entry in pack['rules'].values():
        facts = entry['rule']['facts']
        if set(facts) != set(entry['bindings']):
            raise ValueError('Rule binding inventory mismatch')
        for key,spec in facts.items():
            cid=entry['bindings'][key]
            if cid!=contract(spec) or pack['contracts'][cid]['spec']!=spec:
                raise ValueError('Rule and catalog disagree')
    return pack

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('output',type=Path)
    dest=p.parse_args().output
    dest.write_text(json.dumps(verify(compile_pack()),indent=2,sort_keys=True)+'\n')
