"""Check the two output levels independently and compare bundle and replay entry points."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

import trial_disposition

BENCH = Path(__file__).resolve().parents[1]


class TrialTests(unittest.TestCase):
    def test_evaluate_and_single_patient(self):
        report = trial_disposition.evaluate_frozen()
        self.assertEqual((report['assignments'], report['patient_study_pairs']), (134, 68))
        excluded = [r for r in report['pair_results'] if r['disposition'] == 'NOT_ELIGIBLE_AT_PRESENTATION']
        self.assertEqual(len(excluded), report['pair_dispositions']['NOT_ELIGIBLE_AT_PRESENTATION'])
        ids = [i for r in excluded for i in r['assigned_criteria']]
        self.assertEqual(len(set(ids)), len(ids))
        self.assertEqual(report['criteria_in_excluded_pairs'], sorted(ids))
        for case in excluded:
            self.assertTrue(case['decisive_findings'])
            for finding in case['decisive_findings']:
                self.assertEqual(finding['receipt']['subject'], case['subject'])
                self.assertEqual(finding['receipt']['study'], case['study'])
        examples = {r['study']: r for r in excluded}
        for study in ['NCT02467309','NCT02618655']:
            r=examples[study]
            bundle=BENCH/'round12/export/bundles'/(r['subject'].split('/')[1]+'.json')
            result = subprocess.run([sys.executable, '-B', str(BENCH.parent/'pocketmd.py'), 'trial-disposition',
                                     '--subject', r['subject'], '--study', study, '--bundle', str(bundle)],
                                    capture_output=True, text=True, check=True)
            single=json.loads(result.stdout)
            self.assertEqual(single['disposition'], r['disposition'])
            self.assertEqual([x['gate'] for x in single['decisive_findings']],
                             [x['gate'] for x in r['decisive_findings']])
        self.assertTrue(all(r['disposition'] in ('CONTINUE_SCREENING','NOT_ELIGIBLE_AT_PRESENTATION')
                            for r in report['pair_results']))

if __name__=='__main__':
    unittest.main()
