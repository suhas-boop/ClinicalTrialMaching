import unittest
from narrative_evidence import extract,supports

class VignetteTests(unittest.TestCase):
    def test_patient_age(self):
        self.assertEqual(extract('0. A 21-year-old college student undergoes colonoscopy.')['facts']['age_years']['value'],21)
    def test_no_relative(self):
        for s in ['A 40-year-old mother presents with her child.', 'His mother was 40 years old.','A 40-year-old woman previously treated for illness is her mother.']:
            self.assertEqual(extract('0. '+s)['facts'],{})
    def test_no_age_from_family_history_or_future(self):
        self.assertFalse(extract('0. The patient presents today.\n1. His 45-year-old father presents later.')['facts'])
    def test_group(self):
        self.assertEqual(extract('0. A group of 14 people travels together.')['scope'],'multiple_subjects')
    def test_no_history_or_consent_by_silence(self):
        self.assertEqual(extract('0. The patient will provide informed consent.')['facts'],{})
    def test_numbered_source_integrity(self):
        for s in ('0. First.\n0. Second.','1. No first sentence.'):
            with self.assertRaises(ValueError):extract(s)
    def test_no_different_anchor(self):
        spec=dict(kind='number',role='record',unit='a',scope='age at first dose')
        self.assertFalse(supports('age_years',spec))
