"""Source-qualified exclusion checks using the actual note writer, FHIR reader and matcher."""
import sys
import unittest
from pathlib import Path

BENCHMARK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCHMARK / 'round12'))
from intake import plain_chart
from screen import read_json, verify, screen, R11


class PopulationScopeTests(unittest.TestCase):
    pack = verify(read_json(R11 / 'compiled.json'))

    def evaluate(self, criterion, lines):
        study = self.pack['rules'][criterion]['source']['trial_id']
        def line(text):
            if isinstance(text, tuple):
                field, value = text
                return f'Study {study} | Reproductive assessment / {field}: {value}.'
            return text
        chart, _ = plain_chart('scope-test','\n'.join(map(line,lines)),'2026-01-01T00:00:00Z')
        resources = [e['resource'] for e in chart['entry']]
        return screen(resources,'Patient/scope-test',self.pack,study,criterion)['criteria'][criterion]

    group = 'Participant is in the protocol-defined women population'
    child = 'Patient is a woman of childbearing age'
    adequate = 'Adequate contraception documented'
    pregnant = 'A 32-year-old woman at 18 weeks gestation in her first pregnancy presents for assessment.'

    def test_no_demographic_pregnancy_or_applicability_inference(self):
        original = read_json(BENCHMARK/'round9/notes.json')['sigir-201417']
        v = self.evaluate('322',[original])
        self.assertEqual(v['state'],'MISSING_DATA')
        for k in ['pregnant','in_protocol_women_population','adequate_contraception','woman_of_childbearing_age']:
            self.assertIsNone(v['facts'][k]['value'])

    def test_either_exclusion_branch(self):
        for lines in [[self.pregnant], [self.pregnant,(self.group,'yes')], [(self.child,'yes'),(self.adequate,'no')]]:
            v = self.evaluate('322',lines)
            self.assertEqual(v['state'],'NOT_MET')
            self.assertTrue(v['evidence'])

    def test_false_for_both_branches(self):
        v = self.evaluate('322',[(self.group,'no')])
        self.assertEqual(v['state'],'MET')
        self.assertEqual(v['source_sentences'],[0])
        self.assertIsNone(v['facts']['pregnant']['value'])

    def test_scope_conflict_family_and_wrong_study(self):
        for lines in [[(self.group,'yes'),(self.group,'no')],
                      [(self.group,'no'),(self.child,'yes'),(self.adequate,'no')],
                      ['Study NCT00000000 | Reproductive assessment / '+self.group+': yes.'],
                      ['Family history:',(self.group,'yes')]]:
            v = self.evaluate('322',lines)
            self.assertIsNone(v['facts']['in_protocol_women_population']['value'])
            self.assertEqual(v['state'],'MISSING_DATA')

    def test_parallel_qualifiers(self):
        for criterion in ['132','795']:
            v=self.evaluate(criterion,['A 22-year-old male presents today.'])
            self.assertEqual(v['state'],'MISSING_DATA')
            v=self.evaluate(criterion,[(self.group,'no')])
            self.assertEqual(v['state'],'MET')
            self.assertEqual(v['source_sentences'],[0])

if __name__=='__main__':
    unittest.main()
