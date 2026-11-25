"""Recognize explicit English patient assertions under a limited, auditable concept lexicon."""
from collections import defaultdict
import re

# Vocabulary is shared by note intake and the rule binding catalog. Historical assertions
# never satisfy current-disease contracts. Exams and enrollment-relative time windows need
# their own contracts. Aliases below are complete objects of explicit verbs, never substring hits.
CURRENT={
 'cutaneous_ulcer_due_to_burns':'a cutaneous ulcer due to burns',
 'cutaneous_ulcer_due_to_insect_bite':'a cutaneous ulcer due to an insect bite',
 'cutaneous_ulcer_due_to_leishmania':'a cutaneous ulcer due to leishmania',
 'lung_cancer':'lung cancer', 'gastric_carcinoma':'gastric carcinoma|gastric cancer',
 'systemic_lupus_erythematosus':'systemic lupus erythematosus',
 'immune_deficiency':'immunodeficiency|immune deficiency|common variable immunodeficiency',
 'congenital_immunodeficiency':'congenital immunodeficiency', 'hiv':'HIV infection|HIV',
 'tuberculosis':'active tuberculosis|tuberculosis', 'septic_shock':'septic shock',
 'diagnosed_shock':'shock', 'diagnosed_ards':'acute respiratory distress syndrome|ARDS',
 'unipolar_major_depressive_disorder':'unipolar major depressive disorder',
 'unstable_angina':'unstable angina', 'current_uncontrolled_angina':'uncontrolled angina',
 'symptomatic_congestive_heart_failure':'symptomatic congestive heart failure',
 'severe_uncontrolled_ventricular_arrhythmia':'severe uncontrolled ventricular arrhythmia',
 'acute_kidney_disease':'acute kidney disease','acute_liver_disease':'acute liver disease',
 'current_severe_infection':'a severe active infection|a current severe infection',
 'coagulopathy':'coagulopathy','claustrophobia':'claustrophobia','moribund':'a moribund condition',
 'malignant_hypertension':'malignant hypertension','severe_hypertension':'severe hypertension',
 'secondary_hypertension':'secondary hypertension','active_suicidal_ideation':'active suicidal ideation',
 'chest_tube_in_place':'a chest tube in place','menorrhagia':'menorrhagia',
 'tattoos':'tattoos','acute_surgical_abdomen':'an acute surgical abdomen',
 'persistent_vomiting':'persistent vomiting','jaundice':'jaundice','respiratory_distress':'respiratory distress',
 'impaired_consciousness':'impaired consciousness','seizures':'seizures','malaria':'malaria',
 'severe_or_complicated_malaria':'severe malaria|complicated malaria','non_falciparum_species_on_microscopy':'a non-falciparum species on microscopy',
 'abnormal_neurologic_exam':'an abnormal neurologic examination', 'positive_thyroid_peroxidase_antibodies':'positive thyroid peroxidase antibodies',
 'blunt_abdominal_trauma':'blunt abdominal trauma','penetrating_abdominal_trauma':'penetrating abdominal trauma',
 'acute_isolated_epidural_hematoma':'an acute isolated epidural hematoma',
 'traumatic_brain_injury':'a traumatic brain injury|traumatic brain injury',
 'symptomatic_chronic_subdural_hematoma':'a symptomatic chronic subdural hematoma',
 'unexplained_menstrual_irregularity':'unexplained menstrual irregularity',
}
HISTORY={
 'history_of_mi':'myocardial infarction','history_of_gi_bleeding':'gastrointestinal bleeding',
 'history_ischemic_cns_disease':'ischemic CNS disease','history_of_blood_dyscrasia':'blood dyscrasia',
 'previous_deep_brain_stimulation_surgery':'deep brain stimulation surgery',
 'prior_axillary_surgery':'axillary surgery','prior_thyroid_tissue_resection':'thyroid resection',
 'prior_neck_irradiation':'neck irradiation','prior_radioactive_iodine_therapy':'radioactive iodine therapy',
 'prior_celiac_serology':'celiac serology testing','prior_central_venous_puncture_or_catheterization':'central venous catheterization|central venous puncture',
 'any_past_or_current_antipsychotic_treatment':'antipsychotic treatment',
 **{'prior_treatment_'+drug:'treatment with '+drug for drug in ('lithium','methimazole','propylthiouracil','ethionamide','amiodarone','sunitinib')}
}
def reverse(vocab):
    return {alias.lower():key for key,terms in vocab.items() for alias in terms.split('|')}
INDEX={'current':reverse(CURRENT),'history':reverse(HISTORY)}
SUBJECT=r'^(?:the patient|she|he) '
TEMPLATES=[
 ('history',False,r'(?:has no (?:known )?history of|denies (?:any |a )?history of) '),
 ('history',True,r'(?:has a (?:documented )?history of) '),
 ('current',False,r'(?:does not have|denies current|has no current) '),
 ('current',True,r'(?:has|currently has|is diagnosed with|has a current diagnosis of) '),
]
def declared_facts(lines):
    seen=defaultdict(dict)
    for i,line in lines.items():
        for mode,polarity,verb in TEMPLATES:
            m=re.fullmatch(SUBJECT+verb+r'([^.;?!]+)\.?',line.strip(),re.I)
            if m:
                key=INDEX[mode].get(m[1].strip().lower())
                if key:seen[key].setdefault(polarity,[]).append(i)
    return seen
