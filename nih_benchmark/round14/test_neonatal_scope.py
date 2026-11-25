"""Exercise reported neonatal age groups and explicit reproductive assessment via FHIR."""
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'round12'))
from intake import plain_chart
from screen import screen
from catalog import compile_pack, verify

CASE = '55'
NCT = 'NCT02390596'
PREG = f'Study {NCT} | Reproductive assessment / Currently pregnant: '
DAYS = 'Pediatric presentation / Completed days since birth: '
PRETERM = 'Pediatric presentation / Currently a preterm newborn: '

class NeonatalScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = verify(compile_pack())
    def result(self, *lines):
        chart, spans = plain_chart('child', '\n'.join(lines), '2026-01-01T00:00:00Z')
        resources = [item['resource'] for item in chart['entry']]
        result = screen(resources, 'Patient/child', self.pack, NCT, CASE)['criteria'][CASE]
        self.assertLessEqual(set(result['evidence']), {s['resource'] for s in spans})
        return result
    def test_registered_crosswalk(self):
        src = self.pack['rules'][CASE]['source']
        self.assertEqual(src['trial_id'], NCT)
        self.assertEqual(src['linked_registration']['id'], '2014-002715-41')
    def test_days_preterm_and_boundaries(self):
        for report, expected in [
            ([DAYS+'0 days.'], 'NOT_MET'),
            ([DAYS+'27 days.'], 'NOT_MET'),
            ([DAYS+'28 days.', PREG+'no.'], 'MISSING_DATA'),
            ([DAYS+'28 days.', PRETERM+'no.', PREG+'no.'], 'MET'),
            ([DAYS+'28 days.', PRETERM+'yes.', PREG+'no.'], 'NOT_MET'),
            ([DAYS+'0.5 days.', PRETERM+'no.', PREG+'no.'], 'MISSING_DATA'),
            ([DAYS+'258 days.', PREG+'no.'], 'MISSING_DATA'),
            ([DAYS+'259 days.', PREG+'no.'], 'MET'),
            ([PRETERM+'yes.'], 'NOT_MET'),
            ([PREG+'yes.'], 'NOT_MET'),
        ]:
            with self.subTest(report=report):
                self.assertEqual(self.result(*report)['state'], expected)
    def test_original_and_missingness(self):
        original = json.loads((HERE.parent/'round9/notes.json').read_text())['sigir-20144']
        result = self.result(original)
        self.assertEqual(result['state'], 'MISSING_DATA')
        for key in ['current_preterm_newborn','current_age_0_through_27_days']:
            self.assertEqual(result['facts'][key]['state'], 'AVAILABLE')
            self.assertIs(result['facts'][key]['value'], False)
        self.assertEqual(result['facts']['current_pregnancy_exclusion_status_or_documented_nonapplicability']['state'],'MISSING_DATA')
        older = 'A 2-year-old boy presents to the emergency department.'
        self.assertEqual(self.result(older, 'The patient was born at 30 weeks of gestation.', PREG+'no.')['state'], 'MET')
        self.assertEqual(self.result(older, PREG.replace(NCT, 'NCT00000000')+'no.')['state'], 'MISSING_DATA')
        self.assertEqual(self.result(older, PREG+'yes.', PREG+'no.')['state'],'MISSING_DATA')
        applicability = f'Study {NCT} | Reproductive assessment / Pregnancy exclusion documented as not applicable to this participant: '
        self.assertEqual(self.result(older, applicability+'yes.')['state'], 'MET')
        self.assertEqual(self.result(older, applicability+'no.')['state'], 'MISSING_DATA')
        self.assertEqual(self.result(older, applicability+'yes.', PREG+'yes.')['state'], 'MISSING_DATA')
        self.assertEqual(self.result(older, applicability.replace(NCT, 'NCT00000000')+'yes.')['state'], 'MISSING_DATA')
if __name__ == '__main__':
    unittest.main()
