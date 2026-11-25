"""Exercise source scope, intent, and current disposition through public screening functions."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'round12'))
from intake import plain_chart
from screen import R11, read_json, verify, screen

class ConsentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = verify(read_json(R11/'compiled.json'))

    def evaluate(self, case, text):
        study = self.pack['rules'][case]['source']['trial_id']
        bundle, _ = plain_chart('qa', text.replace('RIGHTSTUDY',study), '2026-01-01T00:00:00Z')
        items = [entry['resource'] for entry in bundle['entry']]
        return screen(items,'Patient/qa',self.pack,study,case)['criteria'][case]

    def test_future_only(self):
        note='The patient will provide informed consent, and will comply with the trial protocol without any practical issues.'
        for criterion in ('212','336','632'):
            c=self.evaluate(criterion,note)
            self.assertEqual(c['state'],'MISSING_DATA')
            self.assertEqual(c['evidence'],[])
            for f in c['facts'].values():
                self.assertEqual(f['related_findings'][0]['study_scope'],'unspecified')
                self.assertEqual(f['related_findings'][0]['source_lines'],[0])

    def test_current_encounter_and_study(self):
        for case in ('212','336'):
            for stance,expected in [('gave','MET'),('declined','NOT_MET'),('refused','NOT_MET')]:
                note=f'Study RIGHTSTUDY: the patient {stance} written informed consent at this screening visit.'
                self.assertEqual(self.evaluate(case,note)['state'],expected)
        # Signature and capacity are different evidence contracts.
        self.assertEqual(self.evaluate('632','Study RIGHTSTUDY: she gave written informed consent at this screening visit.')['state'],'MISSING_DATA')

    def test_wrong_subject_or_scope(self):
        for note in [
            'Study NCT00000000: she gave written informed consent at this screening visit.',
            'She gave written informed consent at this screening visit.',
            'Study RIGHTSTUDY: her mother gave written informed consent at this screening visit.',
            'Study RIGHTSTUDY: she gave oral informed consent at this screening visit.',
            'Study RIGHTSTUDY: she gave written informed consent at the previous visit.',
            'Study RIGHTSTUDY: if the patient gave written informed consent at this screening visit.',
        ]:
            self.assertEqual(self.evaluate('212',note)['state'],'MISSING_DATA')

    def test_conflict(self):
        text= ('Study RIGHTSTUDY: she gave written informed consent at this screening visit.\n'
               'Study RIGHTSTUDY: she declined written informed consent at this screening visit.')
        self.assertEqual(self.evaluate('212',text)['state'],'MISSING_DATA')

    def test_scoped_intent(self):
        for tag,expected in [('RIGHTSTUDY', True), ('NCT00000000', False)]:
            result=self.evaluate('212',f'Study {tag}: the patient will provide written informed consent.')
            self.assertEqual(result['state'],'MISSING_DATA')
            related=result['facts']['refused_written_consent'].get('related_findings',[])
            self.assertEqual(bool(related),expected)
            if related:self.assertEqual(related[0]['study_scope'],'matching study')

if __name__=='__main__':
    unittest.main()
