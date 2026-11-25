"""PocketMD TrialGPT source profile. Parse explicitly labelled patient report fields.
Each row names the report section, the finding within it, and its target rule fact.
Section and field must both be present. Source sentences use 'section / field: value'.
No rule, trial identifier, expert label or patient identifier is used for extraction.
"""
from dataclasses import dataclass
import math
import re

# Distinct chart fields can satisfy a single requirement; one observation can also serve
# several rules. No negative status is inferred when a field is absent.
BOOLEAN_FIELDS = """
Index COPD exacerbation screening assessment|COPD diagnosis confirmed as GOLD stage I through IV|index_copd_gold_stage_i_to_iv_confirmed
Index COPD exacerbation screening assessment|Hospitalization required for this exacerbation|index_copd_exacerbation_required_hospitalization
Index COPD exacerbation screening assessment|Dyspnea increased above baseline|index_copd_dyspnea_increased
Index COPD exacerbation screening assessment|Sputum volume increased above baseline|index_copd_sputum_volume_increased
Index COPD exacerbation screening assessment|Sputum purulence increased above baseline|index_copd_sputum_purulence_increased
Screening logistics|Travel for treatment or follow-up geographically impossible|unable_to_travel_for_treatment_or_followup
Pediatric presentation|Currently a preterm newborn|current_preterm_newborn
Reproductive assessment|Currently pregnant|pregnant
Reproductive assessment|Pregnancy exclusion documented as not applicable to this participant|screening_pregnancy_exclusion_documented_inapplicable
Reproductive assessment|Participant is in the protocol-defined women population|in_protocol_women_population
Reproductive assessment|Potential for childbearing|childbearing_potential
Reproductive assessment|Patient is a woman of childbearing age|woman_of_childbearing_age
Reproductive assessment|Adequate contraception documented|adequate_contraception
Lactation assessment|Currently breastfeeding|breastfeeding
Menstrual history|Postmenopausal woman|postmenopausal_woman
Gynecology assessment|Pelvic bulk symptoms|bulk_symptoms
Gynecology assessment|Symptoms attributed to uterine fibroids|symptoms_attributed_to_uterine_fibroids
Screening examination|Healthy volunteer assessment passed|healthy_subject
Hemodynamic assessment|Currently unstable|hemodynamically_unstable
Medication tolerance|Able to take medication by mouth|can_take_oral_medication
Medication tolerance|Can retain oral medication|can_retain_oral_medication
ECG interpretation|Acute ischemic changes|ecg_acute_ischemia
Neurology assessment|Current ischemic CNS disease|current_ischemic_cns_disease
Respiratory support|Receiving mechanical ventilation|receiving_mechanical_ventilation
Respiratory support|Receiving artificial ventilation|on_artificial_ventilation
Medication reconciliation|Currently receiving systemic anticoagulation|systemic_anticoagulation
Language assessment|Unable to speak English|unable_to_speak_english
Language assessment|Unable to speak French|unable_to_speak_french
Insurance verification|Enrolled in social insurance|has_social_insurance
Trial consent log|Written informed consent refused|refused_written_consent
Trial consent log|Consent refused|consent_refused
Trial consent log|No consent on file|consent_absent
Trial consent capacity assessment|Unable to provide written consent|unable_to_provide_written_consent
Perioperative assessment|Requires sedation to remain still|sedation_required_to_hold_still
MRI safety assessment|Metal safety screening failed|failed_mri_metal_screen
Bleeding history|Bleeding in a family member|family_history_of_bleeding
Infant medical history|Prior bleeding in this infant|infant_history_of_bleeding
Childhood hematology history|Early bone marrow failure during childhood|early_bone_marrow_failure_in_childhood
Patient symptom report|Blood visible in urine|patient_reported_hematuria
Presenting dyspnea assessment|Trauma determined to be the cause|traumatic_cause_of_presenting_dyspnea
Fever assessment|Noninfectious etiology established|fever_due_to_noninfectious_cause
Current head CT final report|Cerebral edema|ct_cerebral_edema
Current head CT final report|Diffuse axonal injury|ct_diffuse_axonal_injury
Current head CT final report|Intracranial hemorrhage|ct_intracranial_hemorrhage
Current head CT final report|Entire examination normal|normal_head_ct
Current chest CT final report|Interstitial lung disease|chest_ct_showed_ild
Current chest CT final report|Pulmonary thromboembolism|chest_ct_showed_pulmonary_thromboembolism
Current chest CT final report|Lung cancer|chest_ct_showed_lung_cancer
Current chest CT final report|Active pulmonary tuberculosis|chest_ct_showed_active_tb
Current cranial CT or MRI final report|Confirmed chronic subdural hematoma|chronic_subdural_hematoma_verified_on_ct_or_mri
Neurosurgical assessment|Recurrence of index hematoma|recurrent_hematoma
Neurosurgical assessment|Index chronic subdural hematoma due to meningeosis carcinomatosa|csh_due_to_meningeosis_carcinomatosa
Neurosurgical assessment|Index chronic subdural hematoma due to spinal CSF fistula|csh_due_to_spinal_csf_fistula
Neurosurgical assessment|Index chronic subdural hematoma caused by underlying illness|csh_due_to_underlying_illness
Post-CT or MRI neurologic assessment|Presenting neurologic symptoms established as nonvascular|neurologic_symptoms_nonvascular_origin_after_ct_or_mri
Index pediatric injury history|Child involved in motor vehicle collision|child_involved_in_motor_vehicle_collision_at_index_injury
Index pediatric injury history|Child injured by another rider|child_injured_by_another_rider_at_index_injury
Index injury equipment history|Bicycle fitted with bull bars involved|index_incident_involved_bicycle_with_bull_bars
Preinjury functional assessment|Neurodevelopmental disability greater than mild|greater_than_mild_preinjury_neurodevelopmental_disability
Hospital admission cognitive screen|Impairment documented on admission screening|cognitive_impairment_on_admission_screen
Current operative record|Emergency laparotomy underway|undergoing_emergency_laparotomy
Trauma surgical plan|Open laparotomy with primary closure required for abdominal trauma|open_laparotomy_required_for_abdominal_trauma_with_primary_closure
Acute abdomen surgical plan|Open laparotomy with primary closure required for acute surgical abdomen|open_laparotomy_required_for_acute_surgical_abdomen_with_primary_closure
Study timeline review|First surgery occurred before study start|first_surgery_before_study_start
Encounter disposition|Transferred to observation unit|transferred_to_observation_unit
Admission attribution|Worsening heart failure was primary reason for admission|worsening_heart_failure_primary_admission_reason
Hospital course assessment|Significant heart failure symptoms developed during admission for another reason|significant_heart_failure_symptoms_developed_in_hospital_initially_admitted_for_other_reason
Study pedigree|Patient is sibling of index subject|sibling_of_index_subject
Study pedigree|Patient is parent of index subject|parent_of_index_subject
Index subject IV glucose tolerance test|Insulin resistance established|index_insulin_resistance_on_ivgtt
Index subject oral glucose tolerance test|Insulin resistance established|index_insulin_resistance_on_ogtt
Specimen inventory for index sample|Aliquot available|aliquot_available
Specimen quality review for index sample|Aliquot suitable for testing|aliquot_suitable_for_testing
2007HPVASCUS30 specimen verification|Linked aliquot has valid APTIMA HPV Tigris result|aliquot_with_valid_aptima_hpv_tigris_result_from_2007HPVASCUS30
Nephrology treatment timeline|Maintenance hemodialysis after central venous catheterization|maintenance_hemodialysis_after_central_venous_catheterization
Study medication review|Currently taking unlicensed investigational aspergillosis drug|current_unlicensed_investigational_aspergillosis_drug
Antifungal reaction history|Prior allergy hypersensitivity or serious reaction to azole or echinocandin|prior_azole_or_echinocandin_allergy_hypersensitivity_or_serious_reaction
Enrollment medication reconciliation|Lipid lowering drugs and doses stable throughout six weeks immediately before enrollment|lipid_lowering_regimen_stable_six_weeks_immediately_before_enrolment
Screening infection timeline|Active severe infection in four weeks before screening|active_severe_infection_within_four_weeks_before_screening
Screening infection timeline|Active severe infection between screening and baseline|active_severe_infection_between_screening_and_baseline
"""
# unit, accepted printed unit, lower/upper bound, integer, standard code if verified
QUANTITIES = [
 ('Pediatric presentation','Completed days since birth','completed_postnatal_days','d','days',0,None,True,None),
 ('Index COPD exacerbation screening assessment','Elapsed time from exacerbation onset at presentation','index_copd_exacerbation_days_since_onset_at_presentation','d','days',0,None,False,None),
 ('Presentation laboratory results','Serum creatinine molar concentration','serum_creatinine_umol_l','umol/L','umol/L',0,None,False,'14682-9'),
 ('Coagulation assay','Platelet-poor plasma INR','inr','1','',0,None,False,'6301-6'),
 ('Arterial blood gas','PaCO2','paco2_mmhg','mm[Hg]','mmHg',0,None,False,'2019-8'),
 ('Neurologic examination','Glasgow Coma Scale motor score','gcs_motor','1','',1,6,True,None),
 ('Birth record','Gestation at birth','gestation_at_birth_weeks','wk','weeks',0,None,False,None),
 ('Performance assessment','WHO performance status','who_performance_status','1','',0,4,True,None),
 ('Asthma history','Exacerbation frequency','asthma_exacerbations_per_week','/wk','per week',0,None,False,None),
 ('Blood microscopy','Malaria parasite density','parasites_per_ml','/mL','parasites/mL',0,None,False,None),
 ('Medication history','Duration of lipid lowering treatment','lipid_lowering_treatment_months','mo','months',0,None,False,None),
]
COURSE_SCOPE=('continuous days of administered voriconazole, itraconazole, posaconazole, caspofungin, micafungin, '
              'anidulafungin, amphotericin B or its lipid formulation, for the index probable or proven invasive '
              'aspergillosis episode, immediately preceding randomization')
DRUGS=('voriconazole','itraconazole','posaconazole','caspofungin','micafungin','anidulafungin',
       'amphotericin B','lipid formulation of amphotericin B')

@dataclass(frozen=True)
class Field:
    section:str
    name:str
    facts:tuple
    kind:str='boolean'
    unit:str=''
    printed_unit:str=''
    low:float=0
    high:float|None=None
    integer:bool=False
    standard:str|None=None

    @property
    def code(self):
        return 'cf-'+re.sub('[^a-z0-9]+','-',(self.section+' '+self.name).lower()).strip('-')

    @property
    def context(self):
        return self.section+' / '+self.name

FIELDS=[]
for row in BOOLEAN_FIELDS.strip().splitlines():
    section,name,keys=row.split('|')
    FIELDS.append(Field(section,name,tuple(keys.split(','))))
for section,name,key,unit,printed,low,high,integer,standard in QUANTITIES:
    FIELDS.append(Field(section,name,(key,),'quantity',unit,printed,low,high,integer,standard))
SKIN=Field('Dermatology examination','Fitzpatrick phototype',('fitzpatrick_I','fitzpatrick_II','fitzpatrick_III'),'category')
MARITAL=Field('Social history','Current marital status',('unmarried',),'category')
CATEGORIES={SKIN:{v:v for v in ('I','II','III','IV','V','VI')},MARITAL:{v:v for v in ('married','never married','divorced','widowed')}}
FIELDS.extend(CATEGORIES)
for drug in DRUGS:
    FIELDS.append(Field('Randomization medication administration review',
                        f'Entire qualifying course consisted solely of continuous {drug} administered for the index probable or proven invasive aspergillosis immediately before randomization',
                        ('qualifying_antifungal_course_days',),'quantity','d','days',0,None,True))
BY_NAME={f.context.casefold():f for f in FIELDS}
BY_CODE={f.code:f for f in FIELDS}
if len(BY_NAME)!=len(FIELDS) or len(BY_CODE)!=len(FIELDS):raise ValueError('Duplicate chart field')

def allowed_number(v,f):
    return (type(v) in (float,int) and math.isfinite(v) and v>=f.low and
            (f.high is None or v<=f.high) and (not f.integer or v==int(v)))

def parse_field(line):
    name,sep,raw=line.rstrip('.').partition(': ')
    f=BY_NAME.get(name.casefold())
    if not sep or f is None:return None
    if f.kind=='boolean':
        choices={'yes':True,'no':False}
        if raw.lower() in choices:return f,choices[raw.lower()]
    elif f.kind=='category':
        options={v.casefold():v for v in CATEGORIES[f]}
        if raw.casefold() in options:return f,options[raw.casefold()]
    else:
        suffix=' '+f.printed_unit if f.printed_unit else ''
        match=re.fullmatch(r'(\d+(?:\.\d+)?)'+re.escape(suffix),raw)
        if match:
            value=float(match[1])
            if allowed_number(value,f):return f,value
    return None

STUDY_TAG='urn:pocketmd:trialgpt:source-study'
STUDY_SECTIONS={'Index COPD exacerbation screening assessment','Screening logistics','Trial consent log','Trial consent capacity assessment','Screening examination',
                'Study timeline review','Study pedigree','Index subject IV glucose tolerance test','Index subject oral glucose tolerance test',
                'Specimen inventory for index sample','Specimen quality review for index sample','2007HPVASCUS30 specimen verification',
                'Study medication review','Enrollment medication reconciliation','Screening infection timeline','Randomization medication administration review',
                'Reproductive assessment'}

# Alternate narrative forms assert an actual finding in the selected chart. Full
# sentences prevent family history, proposed tests and uncertain modifiers leaking in.
NARRATIVE=[
 (r'The patient (is|is not) currently breastfeeding','breastfeeding','is'),
 (r'The patient (is|is not) hemodynamically unstable','hemodynamically_unstable','is'),
 (r'The patient (is|is not) currently receiving mechanical ventilation','receiving_mechanical_ventilation','is'),
 (r'The patient (is|is not) currently receiving systemic anticoagulation','systemic_anticoagulation','is'),
 (r'The patient (can|cannot) retain oral medications','can_retain_oral_medication','can'),
 (r'The patient (can|cannot) take medication by mouth','can_take_oral_medication','can'),
 (r'The patient (reports|denies) blood in the urine','patient_reported_hematuria','reports'),
 (r'The patient (cannot|can) speak French','unable_to_speak_french','cannot'),
 (r'The patient (cannot|can) speak English','unable_to_speak_english','cannot'),
 (r'The current head CT (shows|shows no) intracranial hemorrhage','ct_intracranial_hemorrhage','shows'),
 (r'The current head CT (shows|shows no) cerebral edema','ct_cerebral_edema','shows'),
 (r'The current head CT (is normal|is abnormal)','normal_head_ct','is normal'),
 (r'The current chest CT (shows|shows no) interstitial lung disease','chest_ct_showed_ild','shows'),
]
# Alternative documented measurement and modality-specific report sentences.
MEASURE_SENTENCES=[
    ('serum_creatinine_umol_l',r'(?:Presentation )?serum creatinine (?:is|was) ([0-9.]+) (?:µ|μ|u)mol/L'),
    ('paco2_mmhg',r'Arterial blood gas (?:showed|shows) (?:a )?PaCO2 of ([0-9.]+) mmHg'),
    ('inr',r'Platelet-poor plasma INR (?:is|was) ([0-9.]+)'),
    ('gcs_motor',r'(?:Glasgow Coma Scale|GCS) motor (?:score|subscore) (?:is|was) ([0-9.]+)(?:/6)?'),
    ('gestation_at_birth_weeks',r'The patient was born at ([0-9.]+) weeks(?: of gestation)?'),
    ('parasites_per_ml',r'Blood microscopy (?:showed|shows) ([0-9.]+) malaria parasites/mL'),
    ('who_performance_status',r'WHO performance status (?:is|was) ([0-9.]+)'),
    ('asthma_exacerbations_per_week',r'The patient (?:has|reports) ([0-9.]+) asthma exacerbations per week'),
    ('lipid_lowering_treatment_months',r'The patient has (?:taken|received) lipid.lowering treatment for ([0-9.]+) months'),
]
def narrative_value(text):
    line=text.removesuffix('.')
    for field in (SKIN,MARITAL):
        pat=(r'(?:The patient has )?Fitzpatrick skin type (I|II|III|IV|V|VI)' if field==SKIN
             else r'The patient is (married|divorced|widowed|never married)')
        m=re.fullmatch(pat,line,re.I)
        if m:return field,(m[1].upper() if field==SKIN else m[1].lower())
    for key,pat in MEASURE_SENTENCES:
        m=re.fullmatch(pat,line,re.I)
        if m and re.fullmatch(r'[0-9]+(?:[.][0-9]+)?',m[1]):
            field=next(f for f in FIELDS if key in f.facts)
            v=float(m[1])
            if allowed_number(v,field):return field,v
    for f in FIELDS:
        if f.section not in {'Current chest CT final report','Current head CT final report'}:continue
        if f.name=='Entire examination normal':continue
        modality=f.section.removeprefix('Current ').removesuffix(' final report')
        for verb,positive in [('shows',True),('shows no',False),('is negative for',False)]:
            if line.casefold()==f'The current {modality} {verb} {f.name}'.casefold():return f,positive
    return None

def from_line(text):
    study=None
    tag=re.fullmatch(r'Study (NCT\d{8}) \| (.+)',text)
    if tag:study,text=tag.groups()
    answer=parse_field(text) or narrative_value(text)
    if not answer:
        for pattern,key,positive in NARRATIVE:
            m=re.fullmatch(pattern,text.removesuffix('.'),re.I)
            if m:
                field=next(f for f in FIELDS if key in f.facts)
                answer=(field,m[1].casefold()==positive)
                break
    if not answer:return None
    field,value=answer
    if field.section in STUDY_SECTIONS and not study:return None
    return field,value,study
