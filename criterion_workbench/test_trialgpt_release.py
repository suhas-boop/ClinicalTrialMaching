from contextlib import closing
import json
from pathlib import Path
import sys
import unittest
from copy import deepcopy
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'nih_benchmark/round8'))
from run import abstract,build,controls,packet,fingerprint
from bindings import make_packet
from evidence_review import screen
from record_search import connect,import_bundle,retrieve

class ReleaseChecks(unittest.TestCase):
    def test_conditional_french_does_not_apply_to_all_pregnancies(self):
        entry=build()['795'];rules={'795':entry['rule']};v=fingerprint(entry);s=entry['source']['trial_id']
        for known,want in [({'pregnant':True},'MISSING_DATA'),({'pregnant':True,'unable_to_speak_french':False},'MET'),
                           ({'pregnant':True,'unable_to_speak_french':True},'MISSING_DATA'),
                           ({'in_protocol_women_population':True,'pregnant':True,'unable_to_speak_french':True},'NOT_MET'),
                           ({'in_protocol_women_population':False,'pregnant':True,'unable_to_speak_french':True},'MET'),({'pregnant':False},'MET')]:
            p=make_packet(rules,{'795':known},s,v)
            self.assertEqual(screen(rules,p,s,v)['criteria']['795']['state'],want)
    def test_prognosis_arrival_revises_without_rule_change(self):
        entry=build()['957'];rules={'957':entry['rule']};v=fingerprint(entry);s=entry['source']['trial_id']
        p=make_packet(rules,{},s,v);chart=make_packet(rules,{'957':{'estimated_remaining_life_days':6}},s,v)
        archive=chart['bundle']
        with closing(connect(':memory:')) as db:
            self.assertEqual(retrieve(db,rules,p,s,v)['after']['957']['state'],'INVESTIGATOR_ACTIONS')
            import_bundle(db,archive);out=retrieve(db,rules,p,s,v)
            self.assertEqual(out['after']['957']['state'],'NOT_MET')
            self.assertEqual(len(out['after']['957']['evidence']),2)
            self.assertEqual(import_bundle(db,archive),0)
            self.assertEqual(retrieve(db,rules,p,s,v),out)
        for wrong in ['author','performer','subject']:
            copy=deepcopy(archive)
            for e in copy['entry'][3:]:
                r=e['resource']
                if wrong in r:r[wrong]=[{'reference':'Organization/unknown'}] if wrong!='subject' else {'reference':'Patient/other'}
            with closing(connect(':memory:')) as db:
                import_bundle(db,copy);state=retrieve(db,rules,p,s,v)['after']['957']['state']
                self.assertNotIn(state,['MET','NOT_MET'])
    def test_group_never_returns_patient_decision(self):
        entry=build()['495'];r={'495':entry['rule']};v=fingerprint(entry);s=entry['source']['trial_id']
        p=make_packet(r,{'495':{'birth_weight_kg':1.1}},s,v)
        p['context'].update(source_scope='multiple_subjects',source_sha256='x')
        out=screen(r,p,s,v)
        self.assertEqual(out['criteria']['495']['state'],'SOURCE_SCOPE_HOLD')
        self.assertEqual(out['requests'][0]['route'],'identify_subject')
    def test_double_negation_exclusion(self):
        e=build()['414'];r={'414':e['rule']};s=e['source']['trial_id'];v=fingerprint(e)
        for val,expected in [(True,'MET'),(False,'NOT_MET')]:
            p=make_packet(r,{'414':{'systemic_lupus_erythematosus':val}},s,v)
            self.assertEqual(screen(r,p,s,v)['criteria']['414']['state'],expected)
    def test_forecast_not_signed_and_no_diagnosis_from_symptoms(self):
        facts,_=abstract('0. A 50-year-old man presents with fever.\n1. The patient will provide informed consent.')
        self.assertFalse({'refused_written_consent','consent_absent','diagnosed_shock'}&facts.keys())
    def test_no_relatives_diagnosis(self):
        f,_=abstract('0. A 20-year-old woman presents with her mother who has common variable immunodeficiency.')
        self.assertNotIn('immune_deficiency',f)
    def test_fhir_document_ids_scoped(self):
        rule=build()['44']['rule'];rs={'44':rule}
        def p(who):
            return packet(rs,'study','v',who,{'age_years':(50,[0])},'0. A 50-year-old man presents with fever.')[1]
        self.assertFalse(set(p('a'))&set(p('b')))

class ExplicitPatientAssertions(unittest.TestCase):
    def test_concepts_in_real_source_adapter(self):
        from concept_reader import CURRENT,HISTORY
        for group,vocab in [('current',CURRENT),('history',HISTORY)]:
            for k,terms in vocab.items():
                t=terms.split('|')[0]
                pos='The patient has '+('a history of ' if group=='history' else '')+t+'.'
                neg='The patient '+('has no history of ' if group=='history' else 'does not have ')+t+'.'
                for s,val in [(pos,True),(neg,False)]:
                    facts,_=abstract('0. The patient presents for evaluation.\n1. '+s)
                    self.assertEqual(facts[k],(val,[1]),k)
                for s in [pos.replace('The patient','The mother'),pos.replace(' has ',' may have '),
                          pos.replace(t,t+' if the culture returns positive')]:
                    self.assertNotIn(k,abstract('0. The patient presents.\n1. '+s)[0],k)
                self.assertNotIn(k,abstract('0. The patient presents.\n1. '+pos+'\n2. '+neg)[0],k)
    def test_unmentioned_diagnosis_does_not_fail(self):
        self.assertNotIn('lung_cancer',abstract('0. The patient has a lung mass.')[0])
        self.assertNotIn('tuberculosis',abstract('0. The patient has a history of tuberculosis.')[0])
    def test_same_name_different_contract(self):
        from note_adapter import admits
        self.assertFalse(admits('lung_cancer',dict(role='record',kind='bool',scope='lung cancer diagnosed before enrollment')))
    def test_creatinine_with_explicit_units(self):
        for text,expected in [('Her serum creatinine is 1.3 mg/dL.',1.3),('Her serum creatinine is 100 umol/L.',None),
                             ('Her mother’s serum creatinine is 1.3 mg/dL.',None)]:
            got=abstract('0. The patient presents.\n1. '+text)[0].get('serum_creatinine_mg_dl')
            self.assertEqual(got[0] if got else None,expected)
