"""Compile source-reviewed rules and patient selectors into one versioned artifact."""
import json
from copy import deepcopy
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
from eligibility_engine import validate
from measurement_families import FAMILIES, check_family_selectors
from clinical_fields import FIELDS, SKIN, MARITAL, STUDY_SECTIONS, COURSE_SCOPE, CATEGORIES

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
    for field in FIELDS:
        for key in field.facts:
            number=field.kind=='quantity'
            spec=fact(key,'number',field.unit,scope=COURSE_SCOPE if key=='qualifying_antifungal_course_days' else None) if number else fact(key)
            mapping=selector('Observation',field.code,field.context,'field_'+field.kind,
                             study_scoped=field.section in STUDY_SECTIONS)
            if field.standard:mapping['coding']=[LOINC,field.standard]
            if number:
                mapping.update(unit=field.unit,minimum=field.low,maximum=field.high,integer=field.integer)
            if field.kind=='category':
                mapping['answers']=list(CATEGORIES[field])
                mapping['true_values']=[key.rsplit('_',1)[1]] if field==SKIN else ['never married','divorced','widowed']
            mappings.setdefault(contract(spec),[]).append(mapping)
    # A clinician may document that pregnancy screening is inapplicable for
    # this participant. Preserve this as a criterion disposition rather than
    # recording a negative pregnancy finding on the patient.
    pregnancy = mappings[contract(fact('pregnant'))]
    inapplicable = mappings[contract(fact('screening_pregnancy_exclusion_documented_inapplicable'))]
    mappings[contract(fact('current_pregnancy_exclusion_status_or_documented_nonapplicability'))] = [
        *pregnancy, *(dict(src, read='negative_on_affirmation') for src in inapplicable)]
    # Completed years only resolve newborn categories outside infancy. Completed
    # postnatal days identify the 0–27 day group, including day zero. Current
    # preterm status can extend beyond 27 days and is a separate, documented fact.
    years = mappings[contract(fact('age_years','number','a'))]
    days = mappings[contract(fact('completed_postnatal_days','number','d'))]
    neonatal = mappings.setdefault(contract(fact('current_age_0_through_27_days')), [])
    preterm = mappings[contract(fact('current_preterm_newborn'))]
    for selectors in (neonatal, preterm):
        selectors.extend(dict(src, whole_age_boundary=[1, None, False]) for src in years)
    neonatal.extend(dict(src, whole_age_boundary=[28, True, False]) for src in days)
    # At >=37 weeks after birth, a current gestational age <37 weeks is impossible.
    preterm.extend(dict(src, whole_age_boundary=[37 * 7, None, False]) for src in days)
    # These specific protocols use the literal population word 'women'. Only
    # an affirmative patient description can satisfy it through this selector.
    population = mappings[contract(fact('in_protocol_women_population'))]
    population.append(selector('Observation', 'explicit_woman_description',
                               'note abstraction', 'affirmative_boolean'))
    # A positive finding in this specific subgroup also establishes membership
    # in its parent group. A negative finding has no such implication.
    childbearing = mappings[contract(fact('woman_of_childbearing_age'))]
    population.extend(dict(s, read='affirmative_boolean') for s in childbearing)
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
    families={name for entry in rules.values() for name in validate(entry['rule'])}
    pack = dict(format_version=1, rules=rules, contracts=catalog,
                measurement_families={name:deepcopy(FAMILIES[name]) for name in sorted(families)})
    return dict(**pack, sha256=fingerprint(pack))

def verify(pack):
    payload = {k:v for k,v in pack.items() if k!='sha256'}
    if payload.get('format_version') != 1 or fingerprint(payload) != pack.get('sha256'):
        raise ValueError('Shared catalog fingerprint mismatch')
    used_families=set()
    for entry in pack['rules'].values():
        for name in validate(entry['rule']):
            check_family_selectors(name,pack['contracts'],entry['bindings'])
            used_families.add(name)
        facts = entry['rule']['facts']
        if set(facts) != set(entry['bindings']):
            raise ValueError('Rule binding inventory mismatch')
        for key,spec in facts.items():
            cid=entry['bindings'][key]
            if cid!=contract(spec) or pack['contracts'][cid]['spec']!=spec:
                raise ValueError('Rule and catalog disagree')
    if pack.get('measurement_families',{}) != {name:FAMILIES[name] for name in used_families}:
        raise ValueError('Shared measurement families disagree with the reviewed definitions')
    return pack

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('output',type=Path)
    dest=p.parse_args().output
    dest.write_text(json.dumps(verify(compile_pack()),indent=2,sort_keys=True)+'\n')
