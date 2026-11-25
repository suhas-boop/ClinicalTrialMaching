import unittest
from copy import deepcopy

from exam_bounds import BENCH, HERE, R11, evaluate, read_json, verified_sources, verify
from term_policy import plain_chart


class ExamBoundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = read_json(HERE / 'term_contract.json')
        cls.sources = verified_sources(cls.policy)
        cls.pack = verify(read_json(R11 / 'compiled.json'))

    base = 'A 40-year-old woman presents to the ER.\nOn examination she is tachycardic.'

    def check(self, note=None, case='186', sources=None):
        chart, _ = plain_chart('individual', note or self.base, '2026-01-01T00:00:00Z')
        resources = [e['resource'] for e in chart['entry']]
        return evaluate(resources, 'Patient/individual', self.pack,
                        self.pack['rules'][case]['source']['trial_id'], case,
                        self.policy, self.sources if sources is None else sources)

    def test_exam_and_screening_have_different_scope(self):
        result = self.check()
        self.assertEqual((result['strict'], result['exam_arm']), ('MISSING_DATA', 'MET'))
        evidence = result['evidence']
        self.assertEqual(evidence['evidence_type'], 'inferred lower bound')
        self.assertEqual(evidence['open_lower_bound'], 100)
        self.assertEqual(evidence['study_screening'], 'not evaluated')
        self.assertEqual({line['line'] for c in evidence['citations'] for line in c['lines']}, {0, 1})

    def test_no_supported_amount_despite_related_sign(self):
        for note in [self.base.replace('40-year','8-year'), self.base.replace('she is', 'she was'),
                     self.base.replace('she is', 'she might be'), self.base.replace('she is', 'her father is'),
                     self.base.replace('she is', 'she is not'), self.base.replace('tachycardic', 'tachycardic after exercise'),
                     self.base + '\nShe is no longer tachycardic.']:
            with self.subTest(note=note):
                v = self.check(note)
                self.assertEqual(v['exam_arm'], v['strict'])
                self.assertNotIn('evidence', v)

    def test_no_respiratory_or_unreviewed_promotion(self):
        v = self.check(self.base.replace('tachycardic','tachypneic'), case='187')
        self.assertEqual(v['exam_arm'], 'MISSING_DATA')
        self.assertNotIn('evidence', self.check(sources={}))

    def test_registry_and_changed_predicate(self):
        p = deepcopy(self.policy)
        p['governing_criteria'][0]['registry_sha256'] = 'e' * 64
        with self.assertRaises(ValueError):
            verified_sources(p)
        p = deepcopy(self.policy)
        p['governing_criteria'][0]['predicate']['value'] = 120
        self.assertNotIn('evidence', self.check(sources=verified_sources(p)))

    def test_measurement_precedence_and_unstructured_compact_pulse(self):
        for text in ['P 82/min', 'P:82', 'Vitals show P=82, RR 23.', 'PR 82', 'HR: 82', 'Pulse 82']:
            with self.subTest(numeric=text):
                v = self.check(self.base + '\n' + text)
                self.assertNotIn('evidence', v)
                self.assertNotEqual(v['exam_arm'], 'MET')
        for value, expected in [(89, 'NOT_MET'), (90, 'MET')]:
            v = self.check(self.base + f'\nHeart rate: {value} bpm.')
            self.assertEqual((v['strict'], v['exam_arm']), (expected, expected))
            self.assertNotIn('evidence', v)


if __name__ == '__main__':
    unittest.main()
