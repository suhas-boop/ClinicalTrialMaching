"""Frozen, in-session model-authored interpretation of the blinded criterion texts."""
import json
from pathlib import Path
root=Path(__file__).resolve().parent
def f(name): return {'fact':name}
def anyof(*names): return {'any':[f(k) for k in names]}
def allof(*names): return {'all':[f(k) for k in names]}
def gt(name,n):return {'fact':name,'op':'gt','value':n}
def hold(text):return {'hold':text}
expr={
20:f('unable_to_travel_for_treatment_or_followup'),
25:anyof('severe_hypertension','malignant_hypertension','secondary_hypertension'),
26:anyof('pregnant','childbearing_potential'),
29:gt('serum_creatinine_mg_dl',3.0),
142:allof('symptoms_of_mild_cognitive_impairment','study_personnel_confirm_mci_symptoms'),
145:f('active_suicidal_ideation'),147:f('previous_deep_brain_stimulation_surgery'),
150:allof('enrolled_two_year_blinded_ASA_trial','entered_three_year_ASA_extension'),
154:{'all':[f('healthy_subject'),anyof('fitzpatrick_I','fitzpatrick_II','fitzpatrick_III')]},
155:anyof('visible_skin_disease','tattoos','skin_condition','abnormal_skin_color'),
212:f('refused_written_consent'),217:f('traumatic_cause_of_presenting_dyspnea'),
218:hold('Confirm malformed serum creatinine unit in the supplied excerpt.'),
385:allof('can_take_oral_medication','can_retain_oral_medication'),
396:anyof('history_of_mi','current_uncontrolled_angina','severe_uncontrolled_ventricular_arrhythmia','symptomatic_congestive_heart_failure','unstable_angina','ecg_acute_ischemia'),
397:f('marked_baseline_qt_prolongation'),400:anyof('history_ischemic_cns_disease','current_ischemic_cns_disease'),
401:f('current_or_prior_five_year_malignancy_outside_specified_exceptions'),
402:f('current_severe_infection'),414:{'not':f('systemic_lupus_erythematosus')},
418:f('failed_mri_metal_screen'),419:anyof('claustrophobia','sedation_required_to_hold_still'),
850:gt('asthma_exacerbations_per_week',2),
890:f('cognitive_impairment_on_admission_screen'),919:hold('Definition of severe CDAD referenced above is absent.'),
935:f('enrolling_physician_considers_mycobacterial_culture_likely_positive'),
936:f('positive_sputum_genexpert_mtb_rif'),938:f('willing_to_provide_blood_samples'),
939:f('willing_to_store_samples'),940:anyof('acute_liver_disease','acute_kidney_disease'),
945:f('current_unlicensed_investigational_aspergillosis_drug'),
946:f('listed_antifungal_for_index_probable_or_proven_aspergillosis_over_seven_days_immediately_before_randomization'),
952:allof('on_artificial_ventilation','extubation_unlikely_within_24h_of_entry'),
953:f('prior_azole_or_echinocandin_allergy_hypersensitivity_or_serious_reaction'),
955:f('investigator_identified_unacceptable_risk_from_concomitant_condition'),
957:f('life_expectancy_under_seven_days')}
gates={26:'woman',936:'china_subject'}
def keys(node):
 if 'fact' in node: yield node['fact']
 for v in node.values():
  for child in v if isinstance(v,list) else [v]:
   if isinstance(child,dict):yield from keys(child)
rules={}
for row in json.loads((root/'blind.json').read_text()):
 i=row['annotation_id'];e=expr[i]
 rule={'expression':{'not':e} if row['criterion_type']=='exclusion' else e}
 if i in gates:rule['applies']=f(gates[i])
 rule['facts']={}
 for k in set(keys(e)) | ({gates[i]} if i in gates else set()):
  spec={'kind':'bool','role':'record','label':k,'scope':k.replace('_',' ')}
  if k in ('serum_creatinine_mg_dl','asthma_exacerbations_per_week'):
   spec.update(kind='number',unit='mg/dL' if k.startswith('serum') else '/wk')
  rule['facts'][k]=spec
 rules[str(i)]=rule
(root/'rules.json').write_text(json.dumps(rules,sort_keys=True,indent=2))
