from copy import deepcopy
import unittest

from respiratory import HERE, R11, infer, read_json, verified_sources, verify
from term_policy import plain_chart


class RespiratoryExaminationTest(unittest.TestCase):
    base = 'A 40-year-old woman presents to the ER.\nOn examination she is tachypneic.'

    @classmethod
    def setUpClass(cls):
        cls.policy = read_json(HERE / 'term_contract.json')
        cls.sources = verified_sources(cls.policy)
        cls.pack = verify(read_json(R11 / 'compiled.json'))

    def check(self, note, *, policy=None, sources=None, pack=None):
        bundle, _ = plain_chart('person', note, '2026-01-01T00:00:00Z')
        return infer([e['resource'] for e in bundle['entry']], 'Patient/person',
                     self.pack if pack is None else pack, 'NCT01526382', '187',
                     self.policy if policy is None else policy, self.sources if sources is None else sources)

    def test_bound_at_exam_and_full_disjunction(self):
        result = self.check(self.base)
        self.assertEqual((result['strict'], result['textbook_sensitivity']), ('MISSING_DATA','MET'))
        evidence = result['respiratory_review']
        self.assertEqual(result['supported_exam'], 'MISSING_DATA')
        self.assertEqual(result['lower_cutoff_sensitivity'], 'MISSING_DATA')
        self.assertEqual(evidence['publication_examples'][0]['observed_breaths_per_minute'],18)
        self.assertEqual(evidence['open_lower_bound'], 20)
        self.assertEqual(evidence['sufficient_leaf'], {'fact':'respiratory_rate','op':'ge','value':20})
        self.assertIn(evidence['sufficient_leaf'], evidence['comparison']['any'])
        self.assertFalse(evidence['alternative_definition']['proves_same_leaf'])
        self.assertEqual(evidence['study_screening'], 'not evaluated')
        self.assertEqual({i['line'] for c in evidence['citations'] for i in c['lines']}, {0,1})

    def test_subject_context_and_negation(self):
        for note in [self.base.replace('40-year','7-year'), self.base.replace('she is','her mother is'),
                     self.base.replace('she is','she was'), self.base.replace('she is','she may be'),
                     self.base.replace('she is','she is not'), self.base + '\nShe is no longer tachypneic.',
                     self.base.replace('tachypneic','tachypneic after exercise'), 'On examination she is tachypneic.']:
            with self.subTest(note=note):
                self.assertEqual(self.check(note)['textbook_sensitivity'], 'MISSING_DATA')

    def test_measured_value_precedence_and_compact_numbers(self):
        for value, expected in [(19,'MISSING_DATA'), (20,'MET')]:
            result = self.check(self.base + f'\nRespiratory rate: {value} breaths/min.')
            self.assertEqual((result['strict'], result['textbook_sensitivity']), (expected, expected))
            self.assertNotIn('respiratory_review', result)
        # Reported adult uses of this term with 18/min require explicit rates to take priority.
        for line in ['Respiratory rate: 18 breaths/min.', 'Tachypneic (18 breaths per minute).']:
            r = self.check(self.base + '\n' + line)
            self.assertEqual((r['supported_exam'], r['textbook_sensitivity']), ('MISSING_DATA','MISSING_DATA'))
        for field in ['R 17/min','R: 17','RR18','Resp rate=17','She is at 15 breaths/min.']:
            with self.subTest(field=field):
                self.assertEqual(self.check(self.base + '\n' + field)['textbook_sensitivity'], 'MISSING_DATA')

    def test_all_three_alternatives(self):
        for line in ['The arterial blood gas showed PaCO2 32 mmHg.','She is on a mechanical ventilator.']:
            result=self.check(self.base + '\nRespiratory rate: 18 breaths/min.\n' + line)
            self.assertEqual(result['strict'], 'MET', line)
            self.assertEqual(result['textbook_sensitivity'], 'MET')
            self.assertNotIn('respiratory_review', result)
        all_false=self.check(self.base + '\nRespiratory rate: 18 breaths/min.\nThe arterial blood gas showed PaCO2 39 mmHg.\nShe is breathing spontaneously without mechanical ventilation.')
        self.assertEqual((all_false['strict'],all_false['textbook_sensitivity']),('NOT_MET','NOT_MET'))

    def test_only_reviewed_expression_can_be_promoted(self):
        self.assertEqual(self.check(self.base,sources={})['textbook_sensitivity'],'MISSING_DATA')
        pack=deepcopy(self.pack)
        expression=pack['rules']['187']['rule']['expression']
        expression['all']=expression.pop('any')
        result=self.check(self.base, pack=pack)
        self.assertEqual(result['textbook_sensitivity'], 'MISSING_DATA')
        self.assertNotIn('respiratory_review',result)

if __name__ == '__main__':
    unittest.main()
