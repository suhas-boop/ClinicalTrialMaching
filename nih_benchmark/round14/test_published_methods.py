"""Protocol-grounded unit, polarity, cardinality and index-presentation controls."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'round12'))
from intake import plain_chart
from screen import screen
from catalog import compile_pack, verify, fingerprint
from eligibility_engine import validate


class PublishedMethodsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = verify(compile_pack())

    def evaluate(self, number, text):
        study = self.pack['rules'][number]['source']['trial_id']
        chart, spans = plain_chart('test', text, '2026-01-01T00:00:00Z')
        resources = [entry['resource'] for entry in chart['entry']]
        result = screen(resources, 'Patient/test', self.pack, study, number)['criteria'][number]
        if result['state'] in {'MET', 'NOT_MET'}:
            references = {item['resource'] for item in spans}
            self.assertTrue(result['evidence'])
            self.assertLessEqual(set(result['evidence']), references)
        return result['state']

    def test_creatinine(self):
        for note, expected in [
            ('Serum creatinine is 250 umol/L.', 'MET'),
            ('Serum creatinine is 250.1 µmol/L.', 'NOT_MET'),
            ('Serum creatinine is 2.82 mg/dL.', 'MET'),
            ('Serum creatinine is 2.83 mg/dL.', 'NOT_MET'),
            ('Serum creatinine is 2.82 mg/dL. Serum creatinine is 251 umol/L.', 'MISSING_DATA'),
            ('Serum creatinine is 3.0.', 'MISSING_DATA'),
            ('Serum creatinine is 3 mg/dL in urine.', 'MISSING_DATA'),
            ('Serum creatinine is 3 mg/dL or 2.5 mg/dL.', 'MISSING_DATA'),
            ('Serum creatinine is 3.0 mg/dL after dialysis.', 'MISSING_DATA'),
            ('Mother has a serum creatinine of 3 mg/dL.', 'MISSING_DATA'),
            ('Serum creatinine was 3 mg/dL last year.', 'MISSING_DATA'),
            ('Serum creatinine is 3 mg/dL. Serum creatinine is 1 mg/dL. Serum creatinine is 100 umol/L.', 'MISSING_DATA'),
            ('Urine creatinine is 251 umol/L.', 'MISSING_DATA'),
            ('The CBC was normal.', 'MISSING_DATA'),
        ]:
            with self.subTest(note=note):
                self.assertEqual(self.evaluate('218', note), expected)

    def test_thresholds_belong_to_the_rule(self):
        pack=deepcopy(self.pack)
        entry=pack['rules']['218']
        by_unit=entry['rule']['expression']['not']['same_measurement']
        for form in by_unit:
            form['value'] *= 2
        note='Serum creatinine is 3 mg/dL.'
        bundle,_ = plain_chart('test',note,'2026-01-01T00:00:00Z')
        resources=[x['resource'] for x in bundle['entry']]
        def result(p):
            return screen(resources,'Patient/test',p,entry['source']['trial_id'],'218')['criteria']['218']['state']
        self.assertEqual(result(self.pack),'NOT_MET')
        self.assertEqual(result(pack),'MET')
        self.assertEqual(self.pack['contracts'],pack['contracts'])
        self.assertEqual(set(entry['rule']['facts']),{'serum_creatinine_mg_dl','serum_creatinine_umol_l'})
        # Wire values must satisfy the shared validation even when no conversion is needed.
        observed=next(r for r in resources if r['resourceType']=='Observation')
        q=observed['valueQuantity']
        for override in [{'value':-1},{'value':True},{'code':'ug/mL'},{'comparator':'>'}]:
            saved=deepcopy(q)
            q.update(override)
            self.assertEqual(result(self.pack),'MISSING_DATA')
            q.clear();q.update(saved)
        invalid_rule=deepcopy(entry['rule'])
        invalid_rule['expression']['not']['same_measurement'][0]['op']='lt'
        with self.assertRaises(ValueError):
            validate(invalid_rule)

    def test_measurement_family_guards(self):
        source=self.pack['rules']['218']['rule']
        wrong=deepcopy(source)
        age={'kind':'number','label':'age_years','role':'record','scope':'age years','unit':'a'}
        wrong['facts']['age_years']=age
        wrong['expression']['not']['same_measurement'][0]['fact']='age_years'
        with self.assertRaisesRegex(ValueError,'reporting form'):
            validate(wrong)
        wrong=deepcopy(source)
        wrong['facts']['serum_creatinine_umol_l']['scope']='urine creatinine in a prior encounter'
        with self.assertRaisesRegex(ValueError,'scope'):
            validate(wrong)
        wrong=deepcopy(source)
        wrong['expression']['not']['family']='unknown'
        with self.assertRaisesRegex(ValueError,'Unknown clinical measurement'):
            validate(wrong)
        # A fresh digest cannot authorize a new concept code or time context.
        for change in [{'coding':['http://loinc.org','30525-0']},{'context':'prior encounter'}]:
            altered=deepcopy(self.pack)
            cid=altered['rules']['218']['bindings']['serum_creatinine_mg_dl']
            altered['contracts'][cid]['native'][0].update(change)
            altered['sha256']=fingerprint({k:v for k,v in altered.items() if k!='sha256'})
            with self.assertRaisesRegex(ValueError,'Unapproved measurement'):
                verify(altered)
        altered=deepcopy(self.pack)
        altered['measurement_families']['presentation_serum_creatinine']['clinical_scope']['specimen']='urine'
        altered['sha256']=fingerprint({k:v for k,v in altered.items() if k!='sha256'})
        with self.assertRaisesRegex(ValueError,'reviewed definitions'):
            verify(altered)

    def test_exacerbation(self):
        fields = [
            'COPD diagnosis confirmed as GOLD stage I through IV',
            'Hospitalization required for this exacerbation',
            'Elapsed time from exacerbation onset at presentation',
            'Dyspnea increased above baseline',
            'Sputum volume increased above baseline',
            'Sputum purulence increased above baseline',
        ]
        for values, study, expected in [
            (['yes','yes','13 days','yes','yes','yes'],'NCT00170222','MET'),
            (['yes','yes','13 days','yes','yes','no'],'NCT00170222','MET'),
            (['yes','yes','13 days','yes','no','yes'],'NCT00170222','MET'),
            (['yes','yes','13 days','no','yes','yes'],'NCT00170222','MET'),
            (['yes','yes','13 days','yes','no','no'],'NCT00170222','NOT_MET'),
            (['yes','yes','14 days','yes','yes','yes'],'NCT00170222','NOT_MET'),
            (['yes','no','4 days','yes','yes','yes'],'NCT00170222','NOT_MET'),
            (['no','yes','4 days','yes','yes','yes'],'NCT00170222','NOT_MET'),
            ([None,'yes','4 days','yes','yes','yes'],'NCT00170222','MISSING_DATA'),
            (['yes','yes','4 days','yes',None,'no'],'NCT00170222','MISSING_DATA'),
            (['yes','yes','4 days','yes','yes','yes'],'NCT00000001','MISSING_DATA'),
        ]:
            with self.subTest(values=values,study=study):
                note = '\n'.join(f'Study {study} | Index COPD exacerbation screening assessment / {field}: {value}.'
                                  for field, value in zip(fields, values) if value)
                self.assertEqual(self.evaluate('437', note), expected)
        self.assertEqual(self.evaluate('437', 'A smoker presents with cough, dyspnea and purulent sputum.'), 'MISSING_DATA')


if __name__ == '__main__':
    unittest.main()
