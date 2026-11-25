"""Exercise note intake, standards-only FHIR binding, and evidence isolation."""
from copy import deepcopy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'round12'))
from intake import plain_chart, LOCAL, LOINC
from screen import screen, read_json, verify, R11

class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = verify(read_json(R11/'compiled.json'))
    def items(self, text):
        b,_ = plain_chart('qa', text, '2026-01-01T00:00:00Z')
        return [x['resource'] for x in b['entry']]
    def run_case(self, items, criterion='186'):
        return screen(items, 'Patient/qa', self.pack, self.pack['rules'][criterion]['source']['trial_id'], criterion)['criteria'][criterion]
    def test_qualitative_only(self):
        items=self.items('On examination she is pale and in moderate discomfort, as well as tachypneic and tachycardic.')
        for criterion,label in [('186','heart_rate'),('187','respiratory_rate')]:
            c=self.run_case(items,criterion)
            self.assertEqual(c['state'],'MISSING_DATA')
            self.assertEqual(c['evidence'],[])
            self.assertIsNone(c['facts'][label]['value'])
            self.assertEqual(c['facts'][label]['related_findings'][0]['source_lines'],[0])
    def test_numeric_update_and_boundary(self):
        for number,expected in [(89,'NOT_MET'),(90,'MET')]:
            items=self.items(f'The patient is tachycardic.\nHeart rate: {number} bpm.')
            c=self.run_case(items)
            self.assertEqual(c['state'],expected)
            self.assertEqual(c['source_sentences'],[1])
    def test_standard_only_quantity(self):
        items=self.items('Heart rate: 90 bpm.')
        obs=next(r for r in items if r['resourceType']=='Observation')
        obs['code']['coding']=[c for c in obs['code']['coding'] if c['system']==LOINC]
        self.assertEqual(self.run_case(items)['state'],'MET')
        for system,code in [(LOINC,'wrong'),(LOCAL,'respiratory_rate')]:
            trial=deepcopy(items)
            ob=next(r for r in trial if r['resourceType']=='Observation')
            ob['code']['coding'].append({'system':system,'code':code})
            self.assertEqual(self.run_case(trial)['state'],'MISSING_DATA')
        obs['valueQuantity']['code']='mg/dL'
        self.assertEqual(self.run_case(items)['state'],'MISSING_DATA')
    def test_wrong_subject_and_scope(self):
        for text in ['His mother is tachycardic.','The patient is not tachycardic.',
                     'Family history:\nShe is tachycardic.', 'The patient may be tachycardic.',
                     'The patient was tachycardic yesterday.']:
            c=self.run_case(self.items(text))
            self.assertNotIn('related_findings',c['facts']['heart_rate'])
        items=self.items('The patient is tachycardic.')
        ob=next(r for r in items if r['resourceType']=='Observation')
        ob['subject']={'reference':'Patient/other'}
        self.assertNotIn('related_findings',self.run_case(items)['facts']['heart_rate'])
if __name__=='__main__':
    unittest.main()
