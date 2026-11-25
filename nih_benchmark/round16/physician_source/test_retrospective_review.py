import sys
import tempfile
import unittest
from pathlib import Path
from retrospective_review import HERE, review, workbook_rows

if len(sys.argv)!=2:
    raise SystemExit('Usage: python test_retrospective_review.py <nih_benchmark>')
BENCH=Path(sys.argv.pop())

class EducationalSourceTests(unittest.TestCase):
    def test_exact_case_and_assertion_type(self):
        output=review(BENCH, HERE/'answers-2014.xlsx')
        self.assertEqual(output['n_patients_or_groups'],29)
        records=output['records']
        self.assertTrue(all(not item['promoted_clinical_assertions'] for item in records.values()))
        self.assertEqual(records['sigir-201421']['differential'], 'Systemic lupus erythematosus (SLE)')
        self.assertEqual(records['sigir-201421']['differential_cell'], 'E22')
        self.assertEqual(records['sigir-201411']['differential_cell'],'E12')
        self.assertTrue(records['sigir-201426']['subject'].startswith('Group/'))
    def test_changed_workbook_rejected(self):
        with tempfile.TemporaryDirectory() as path:
            fake=Path(path)/'answers.xlsx';fake.write_text('fake')
            with self.assertRaises(ValueError):
                workbook_rows(fake)

if __name__=='__main__':
    unittest.main()
