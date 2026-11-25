from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import unittest

from literal_scope import (BENCH, R11, plain_chart, read_json, verify, screen_synthetic_note, replay)

class LiteralScopeControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = verify(read_json(R11/'compiled.json'))
    def run_case(self, note, wrong_person=False, mutate=None, key='322'):
        res = [e['resource'] for e in plain_chart('fictional',note,'2026-01-01T00:00:00Z')[0]['entry']]
        hashes = {'Patient/fictional':sha256(note.encode()).hexdigest()} if not wrong_person else {}
        if mutate:
            mutate(res)
        study = self.pack['rules'][key]['source']['trial_id']
        return screen_synthetic_note(res,'Patient/fictional',self.pack,study,key,hashes)

    def test_trace(self):
        output = self.run_case('A 45-year-old man presents with pain.')
        self.assertTrue(output['used'])
        facts = output['trace']['criteria']['322']['facts']
        self.assertFalse(facts['synthetic_vignette_literal_adult_women_cohort']['value'])
        for k in ('pregnant','adequate_contraception','woman_of_childbearing_age'):
            self.assertIsNone(facts[k]['value'])
        self.assertEqual(output['strict_state'],'MISSING_DATA')

    def test_ambiguous(self):
        for text in ['A 16-year-old male presents with pain.','A 38-year-old male relative presents for the patient.',
                     'A 45-year-old male presents with pain. She is examined.','A 45-year-old male presents with pain. The patient is pregnant.',
                     'A 45-year-old male presents with pain. The patient identifies as a woman.',
                     'A 45-year-old male presents with pain. The patient has a uterus.',
                     'A 45-year-old male presents with pain. A trans man.','Male',
                     'A 45-year-old person presents with pain.','A 45-year-old woman presents with pain.']:
            self.assertFalse(self.run_case(text)['used'],text)

    def test_boundaries(self):
        text='A 45-year-old man presents with pain.'
        self.assertFalse(self.run_case(text,wrong_person=True)['used'])
        self.assertFalse(self.run_case(text,key='55')['used'])
        self.assertFalse(self.run_case(text,key='132')['used'])
        def add_document(items):
            extra=deepcopy(next(r for r in items if r['resourceType']=='DocumentReference'))
            extra['id']='later-note';items.append(extra)
        self.assertFalse(self.run_case(text,mutate=add_document)['used'])
        def assign_gender(items):
            next(r for r in items if r['resourceType']=='Patient')['gender']='female'
        self.assertFalse(self.run_case(text,mutate=assign_gender)['used'])

    def test_input_assignment(self):
        result = replay()
        self.assertEqual(len(result),134)
        self.assertEqual({k for k,v in result.items() if v['used']},{'322'})
        self.assertEqual(sum(v['trace']['criteria'][k]['state'] in ('MET','NOT_MET') for k,v in result.items()),7)
        self.assertEqual(result['322']['trace']['criteria']['322']['source_sentences'],[0])

if __name__=='__main__':
    unittest.main()
