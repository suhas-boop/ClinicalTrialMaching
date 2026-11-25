"""Blinded criterion interpretation, prior to seeing the held-out patient narratives."""
from pathlib import Path
import json
root=Path(__file__).resolve().parent
def f(k):return {'fact':k}
def group(op,*xs):return {op:[f(x) if isinstance(x,str) else x for x in xs]}
def anyof(*xs):return group('any',*xs)
def allof(*xs):return group('all',*xs)
def cmp(k,op,v):return {'fact':k,'op':op,'value':v}
def hold(s):return {'hold':s}
expr={
55:hold('Confirm the scope of preterm and neonatal exclusion in the protocol.'),
81:anyof('active_severe_infection_within_four_weeks_before_screening','active_severe_infection_between_screening_and_baseline'),
108:f('hemodynamically_unstable'),109:f('septic_shock'),111:f('cutaneous_ulcer_secondary_to_enteral_fistula'),
115:anyof('cutaneous_ulcer_due_to_leishmania','cutaneous_ulcer_due_to_insect_bite'),
116:f('cutaneous_ulcer_due_to_burns'),
120:allof(anyof('sibling_of_index_subject','parent_of_index_subject'),anyof('index_insulin_resistance_on_ogtt','index_insulin_resistance_on_ivgtt')),
235:allof(anyof('menorrhagia','bulk_symptoms'),'symptoms_attributed_to_uterine_fibroids'),
239:f('postmenopausal_woman'),328:anyof('infant_history_of_bleeding','family_history_of_bleeding'),
329:f('coagulopathy'),330:f('history_of_gi_bleeding'),332:cmp('gestation_at_birth_weeks','lt',36),
336:anyof('consent_refused','consent_absent'),366:allof(anyof('blunt_abdominal_trauma','penetrating_abdominal_trauma'),'open_laparotomy_required_for_abdominal_trauma_with_primary_closure'),
367:allof('acute_surgical_abdomen','open_laparotomy_required_for_acute_surgical_abdomen_with_primary_closure'),
379:f('pregnant'),460:allof('traumatic_brain_injury',anyof(allof(cmp('gcs','le',8),anyof('ct_intracranial_hemorrhage','ct_cerebral_edema','ct_diffuse_axonal_injury')),allof(cmp('gcs_motor','le',3),'normal_head_ct'))),
467:f('greater_than_mild_preinjury_neurodevelopmental_disability'),
468:allof('acute_isolated_epidural_hematoma','rapid_recovery_expected_after_surgical_removal'),
475:f('child_involved_in_motor_vehicle_collision_at_index_injury'),476:f('child_injured_by_another_rider_at_index_injury'),
477:f('index_incident_involved_bicycle_with_bull_bars'),481:f('permanent_resident_luanshya'),
492:f('born_san_francis_designated_district_hospital_ifakara'),493:f('obvious_severe_congenital_malformation'),
494:f('twin_birth'),495:cmp('birth_weight_kg','lt',1.5),496:f('clinical_signs_of_cerebral_asphyxia'),
497:anyof('clinical_signs_neonatal_infection','clinical_signs_congenital_infection'),
498:hold('Clarify the intended maternal assessment and who determines it.'),
577:allof('moribund','active_treatment_of_any_form_not_considered'),
795:hold('Confirm whether pregnancy and inability to speak French are joint or separate exclusions.'),
985:f('chest_tube_in_place')}
def keys(n):
 if 'fact' in n:yield n['fact']
 for v in n.values():
  for c in v if isinstance(v,list) else [v]:
   if isinstance(c,dict):yield from keys(c)
units={'gestation_at_birth_weeks':'wk','birth_weight_kg':'kg','gcs':'1','gcs_motor':'1'}
rules={}
for row in json.loads((root/'blind.json').read_text()):
 i=row['annotation_id'];e=expr[i];facts={}
 for k in keys(e):
  facts[k]={'label':k,'kind':'bool','role':'record','scope':k.replace('_',' ')}
  if k in units:facts[k].update(kind='number',unit=units[k])
 rules[str(i)]={'expression':{'not':e} if row['criterion_type']=='exclusion' else e,'facts':facts}
(root/'rules.json').write_text(json.dumps(rules,sort_keys=True,indent=2))
