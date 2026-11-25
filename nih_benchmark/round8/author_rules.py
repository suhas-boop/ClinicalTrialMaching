"""Apply source-reviewed updates to earlier typed TrialGPT rule packs, before opening evaluation labels."""
from copy import deepcopy
from pathlib import Path
import json
import hashlib
import sys
HERE=Path(__file__).resolve().parent
DATA=HERE.parent
sys.path.insert(0,str(DATA))
from review_replay import roles
from eligibility_engine import validate
from registry_context import packet as registry_packet

# Each question changes the allowed interpretation or an essential operational definition.
QUESTIONS={
 36:"Which discharge disposition does ‘automatic discharge’ denote, and when must it occur?",
 46:"What interval and screening anchor define a ‘recent’ chest CT?",
 55:"Does a history of preterm birth exclude older children, or does the restriction apply only during the neonatal period?",
 111:"Must the enteral fistula be the documented cause of the ulcer, or is coexistence sufficient?",
 130:"Are eating disorder, substance abuse and psychotic disorder three independent exclusions, or must all coexist?",
 140:"Does pregnancy alone or lactation alone trigger exclusion, or must both be present?",
 184:"Who can designate an ‘other inappropriate situation’, and what documented determination governs exclusion?",
 218:"What unit belongs with the creatinine threshold of 250? The registered text says ‘micro mmol/L’.",
 307:"Are the five surgical pathways exhaustive, and which planned procedures must be documented before volumetry?",
 397:"Can a documented assessment establish marked baseline QT prolongation independently of repeated QTc >450 ms, and what qualifies as repeated?",
 401:"Which listed cancers require documented excision to qualify for the five-year cancer-free exception?",
 437:"Which classification and definitions establish the required type I or II COPD exacerbation?",
 498:"What functional assessment and authorized reviewer establish the maternal reliability criterion?",
 544:"Which findings or authorized assessment establish a ‘severe cardiac condition’ for this study?",
 706:"Do the listed pelvic symptoms all have to be present, or can a subset establish symptomatic pelvic congestion?",
 736:"What exposure duration and continuity qualify corticosteroid therapy as long-term?",
 737:"Does a disorder in any listed gland system exclude the patient, or must all three systems be involved?",
 919:"Please provide the governing passage defining a confirmed severe CDAD case, including the diagnostic and severity requirements."
}
# Published Methods for these two studies provide the missing operational definitions.
PUBLISHED_METHODS = {
    218: dict(trial='NCT00163709', pmid='19293069', url='https://pubmed.ncbi.nlm.nih.gov/19293069/',
              locator='Schneider et al., Ann Intern Med 2009, p. 366, Methods / Setting and Participants',
              interpretation='The serum creatinine threshold is strictly greater than 250 micromol/L or 2.82 mg/dL in the corresponding reported unit.'),
    437: dict(trial='NCT00170222', pmid='19875685', url='https://pubmed.ncbi.nlm.nih.gov/19875685/',
              locator='Daniels et al., Am J Respir Crit Care Med 2010, p. 151, Methods / Setting and Participants',
              interpretation='GOLD classifies the COPD diagnosis. The index exacerbation required hospitalization, began less than 14 days before presentation, and had increases in at least two of dyspnea, sputum volume and sputum purulence (Anthonisen I/II).')
}
COPD_ASSESSMENTS = ('index_copd_gold_stage_i_to_iv_confirmed','index_copd_exacerbation_required_hospitalization')
COPD_SYMPTOMS = ('index_copd_dyspnea_increased','index_copd_sputum_volume_increased','index_copd_sputum_purulence_increased')
COPD_ONSET = 'index_copd_exacerbation_days_since_onset_at_presentation'

def published_rule(number):
    if number == 218:
        # Published limits are spelled in each allowed reporting unit. Both
        # numeric contracts also serve other rules with different thresholds.
        mass = 'serum_creatinine_mg_dl'
        molar = 'serum_creatinine_umol_l'
        limits = [F(mass,op='gt',value=2.82),F(molar,op='gt',value=250)]
        return {'expression':N({'same_measurement':limits,'family':'presentation_serum_creatinine'}),
                'facts':{mass:fact(mass,'number','mg/dL'),molar:fact(molar,'number','umol/L')}}
    # Each field concerns the same study's index presentation. A symptom alone does
    # not document an increase relative to the patient's baseline.
    dyspnea, volume, purulence = [F(k) for k in COPD_SYMPTOMS]
    cardinal = {'any':[{'all':[dyspnea,volume]}, {'all':[dyspnea,purulence]}, {'all':[volume,purulence]}]}
    expressions = [F(k) for k in COPD_ASSESSMENTS] + [F(COPD_ONSET,op='lt',value=14),cardinal]
    facts = {k:fact(k) for k in COPD_ASSESSMENTS + COPD_SYMPTOMS}
    facts[COPD_ONSET] = fact(COPD_ONSET,'number','d')
    return {'expression':{'all':expressions}, 'facts':facts}

ROLE_UPDATES={
 **roles, 'surgeon_decided_craniotomy_intraoperatively':'investigator',
 'extubation_unlikely_within_24h_of_entry':'investigator','typical_chest_pain':'investigator',
 'reports_never_had_sexual_intercourse':'patient',
}
def fact(key,kind='bool',unit=None,role='record',scope=None):
    return dict(label=key,kind=kind,role=role,scope=scope or key.replace('_',' ')) | ({'unit':unit} if unit else {})
def F(key,**comparison):
    return {'fact':key,**comparison}
def N(node):return {'not':node}
def build():
    result={}
    for folder in (DATA,DATA/'round2',DATA/'round3'):
        cases=json.loads((folder/'blind.json').read_text())
        old=json.loads((folder/'rules.json').read_text())
        for case in cases:
            i=case['annotation_id'];rule=deepcopy(old[str(i)])
            for key,spec in rule['facts'].items():
                spec['role']=ROLE_UPDATES.get(key,spec['role'])
            if i in PUBLISHED_METHODS:
                if case['trial_id'] != PUBLISHED_METHODS[i]['trial']:
                    raise ValueError('Published Methods trial mismatch')
                rule=published_rule(i)
            elif i == 55:
                keys = ('current_age_0_through_27_days', 'current_preterm_newborn',
                        'current_pregnancy_exclusion_status_or_documented_nonapplicability')
                rule = {'expression': N({'any': [F(k) for k in keys]}), 'facts': {k: fact(k) for k in keys}}
            elif i in QUESTIONS:
                rule={'facts':{},'expression':{'hold':QUESTIONS[i]}}
            elif i==795:
                rule={'expression':N({'all':[F('pregnant'),F('unable_to_speak_french')]}),
                      'facts':{k:fact(k) for k in ('pregnant','unable_to_speak_french')}}
            elif i==957:
                key='estimated_remaining_life_days'
                rule={'expression':N(F(key,op='lt',value=7)),'facts':{key:fact(key,'number','d','investigator')}}
            elif i==142:
                key='study_personnel_confirm_current_mci_symptoms'
                rule={'expression':F(key),'facts':{key:fact(key,role='investigator')}}
            elif i==946:
                key='qualifying_antifungal_course_days'
                scope=('continuous days of administered voriconazole, itraconazole, posaconazole, caspofungin, micafungin, '
                       'anidulafungin, amphotericin B or its lipid formulation, for the index probable or proven invasive '
                       'aspergillosis episode, immediately preceding randomization')
                rule={'expression':N(F(key,op='gt',value=7)), 'facts':{key:fact(key,'number','d',scope=scope)}}
            # The shared population qualifies the whole prohibited condition.
            if i in {132, 322, 795}:
                group = 'in_protocol_women_population'
                rule['facts'][group] = fact(group)
                rule['expression'] = N({'all': [F(group), rule['expression']['not']]})
            validate(rule)
            source={k:case[k] for k in ('trial_id','criterion_type','criterion_text')}
            if i in PUBLISHED_METHODS:
                source['published_methods'] = PUBLISHED_METHODS[i]
            context=HERE/'context'/(case['trial_id']+'.json')
            if i == 55:
                registration = json.loads(context.read_bytes())['protocolSection']['identificationModule']
                if (registration['nctId'] != case['trial_id'] or registration.get('acronym') != 'KAWAKINRA'
                    or {'id': '2014-002715-41', 'type': 'EUDRACT_NUMBER'} not in registration['secondaryIdInfos']):
                    raise ValueError('KAWAKINRA registry cross-reference mismatch')
                source['linked_registration'] = {
                    'id': '2014-002715-41', 'jurisdiction': 'FR',
                    'url': 'https://www.clinicaltrialsregister.eu/ctr-search/trial/2014-002715-41/FR',
                    'locator': 'E.4 item 1; F.1.1.2 to F.1.1.5; F.3.3.3',
                    'additional_url': 'https://www.clinicaltrialsregister.eu/ctr-search/trial/2014-002715-41/IT',
                    'testing_context': 'Italy and Spain E.4 item 1 condition beta-hCG on appropriateness. A documented study-screening determination of nonapplicability resolves the pregnancy exclusion without a test. No numeric age cutoff is specified.',
                    'interpretation': 'Exclusion concerns current preterm newborns and current newborns aged 0–27 days, as well as current pregnancy. A history of preterm birth by itself does not establish a current newborn age group.'
                }
            if context.exists():
                rec=registry_packet(case['trial_id'],case['criterion_text'],context.read_bytes())
                source['registry']={k:rec[k] for k in ('registry_url','registry_sha256','last_update','criterion_in_eligibility_text')}
            result[str(i)]=dict(source=source,rule=rule)
    return result
