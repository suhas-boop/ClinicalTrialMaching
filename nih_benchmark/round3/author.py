"""Blinded semantic rule drafts for the third panel; the FHIR evaluator itself is unchanged."""
import json
from pathlib import Path
root=Path(__file__).resolve().parent
def F(k):return {'fact':k}
def G(op,*vs):return {op:[F(v) if isinstance(v,str) else v for v in vs]}
def A(*xs):return G('all',*xs)
def O(*xs):return G('any',*xs)
def N(x):return {'not':F(x) if isinstance(x,str) else x}
def C(k,op,n):return {'fact':k,'op':op,'value':n}
def H(s):return {'hold':s}
young=C('age_years','lt',18)
expr={34:F('fever_due_to_noninfectious_cause'),36:H('Clarify the intended meaning of automatic discharge.'),
44:young,45:N('lung_cancer'),46:F('pulmonary_nodule_on_recent_ct'),
130:H('Clarify whether any listed disorder suffices or all must coexist.'),
132:O('pregnant','breastfeeding'),138:F('any_past_or_current_antipsychotic_treatment'),
140:H('Clarify whether pregnancy and lactation are separate exclusions.'),
171:A(C('inr','gt',2),N('systemic_anticoagulation')),174:F('prior_axillary_surgery'),177:F('maintenance_hemodialysis_after_central_venous_catheterization'),
179:F('prior_central_venous_puncture_or_catheterization'),184:H('Identify the assessment and decision maker for other inappropriate situations.'),
185:O('diagnosed_shock','diagnosed_ards'),186:C('heart_rate','ge',90),187:O(C('respiratory_rate','ge',20),C('paco2_mmhg','le',32),'receiving_mechanical_ventilation'),
196:young,203:F('positive_thyroid_peroxidase_antibodies'),226:A('recurrent_hematoma','first_surgery_before_study_start'),
227:O('csh_due_to_spinal_csf_fistula','csh_due_to_meningeosis_carcinomatosa'),
230:A(C('age_years','ge',18),'symptomatic_chronic_subdural_hematoma'),231:F('chronic_subdural_hematoma_verified_on_ct_or_mri'),
232:F('surgeon_decided_craniotomy_intraoperatively'),233:F('csh_due_to_underlying_illness'),
307:H('Verify how the five surgical alternatives, pre-volumetry requirements and optional investigations scope together.'),
322:O('pregnant',A('woman_of_childbearing_age',N('adequate_contraception'))),323:A('immune_deficiency','early_bone_marrow_failure_in_childhood'),
359:F('gastric_carcinoma'),435:O(*['chest_ct_showed_'+k for k in ('lung_cancer','active_tb','pulmonary_thromboembolism','ild')]),
437:F('acute_copd_exacerbation_type_I_or_II_per_GOLD'),454:A(C('age_years','gt',18),'male_or_female','undergoing_emergency_laparotomy'),
502:C('who_performance_status','le',1),517:young,544:F('severe_cardiac_condition'),621:N('has_social_insurance'),
632:F('unable_to_provide_written_consent'),633:young,636:C('lipid_lowering_treatment_months','ge',3),
637:F('lipid_lowering_regimen_stable_six_weeks_immediately_before_enrolment'),640:F('typical_chest_pain'),
653:F('unable_to_speak_english'),671:F('unipolar_major_depressive_disorder'),
706:H('Clarify whether the symptoms define pelvic congestion or are each required.'),
720:F('unexplained_menstrual_irregularity'),722:F('prior_thyroid_tissue_resection'),723:F('prior_neck_irradiation'),
724:F('prior_radioactive_iodine_therapy'),725:O(*['prior_treatment_'+k for k in ('lithium','methimazole','propylthiouracil','ethionamide','amiodarone','sunitinib')]),
726:F('prior_celiac_serology'),734:F('congenital_immunodeficiency'),735:F('hiv'),736:F('long_term_corticosteroids'),
737:H('Clarify whether disorders in any of the three gland systems meet this exclusion.'),
738:F('tuberculosis'),817:F('neurologic_symptoms_nonvascular_origin_after_ct_or_mri'),
860:A('unmarried','reports_never_had_sexual_intercourse'),866:F('aliquot_with_valid_aptima_hpv_tigris_result_from_2007HPVASCUS30'),
867:A('aliquot_available','aliquot_suitable_for_testing'),870:O('worsening_heart_failure_primary_admission_reason','significant_heart_failure_symptoms_developed_in_hospital_initially_admitted_for_other_reason'),
875:O('hospital_admission','transferred_to_observation_unit'),
962:O('severe_or_complicated_malaria','impaired_consciousness','seizures','abnormal_neurologic_exam','jaundice','respiratory_distress','persistent_vomiting','patient_reported_hematuria',C('parasites_per_ml','gt',100000),'non_falciparum_species_on_microscopy'),
965:F('history_of_blood_dyscrasia')}
units={'age_years':'a','heart_rate':'/min','respiratory_rate':'/min','paco2_mmhg':'mm[Hg]','inr':'1','who_performance_status':'1','lipid_lowering_treatment_months':'mo','parasites_per_ml':'/mL'}
def keys(x):
 if 'fact'in x:yield x['fact']
 for v in x.values():
  for c in v if isinstance(v,list) else [v]:
   if isinstance(c,dict):yield from keys(c)
rr={}
for row in json.loads((root/'blind.json').read_text()):
 i=row['annotation_id'];e=expr[i]
 if i==962:e=A('malaria',e)
 facts={}
 for k in keys(e):
  facts[k]={'kind':'bool','role':'record','label':k,'scope':k.replace('_',' ')}
  if k in units:facts[k].update(kind='number',unit=units[k])
 rr[str(i)]={'facts':facts,'expression':N(e) if row['criterion_type']=='exclusion' else e}
(root/'rules.json').write_text(json.dumps(rr,indent=2,sort_keys=True))
