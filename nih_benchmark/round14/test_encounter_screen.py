"""Single-command integration for source-verified, same-encounter FHIR evidence."""
import json
import subprocess
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from record_arrivals import R11, receive, read_json

class EncounterScreenTests(unittest.TestCase):
    def setUp(self):
        self.patient='test-patient'
        self.visit='visit-a'
        self.stamp='2026-01-01T00:00:00Z'
        self.base=receive(self.patient,self.visit,'ED-note','The patient is unwell.',self.stamp)
        self.at=receive(self.patient,self.visit,'vitals-sheet','Heart rate: 90 bpm.\nRespiratory rate: 20/min.',self.stamp)
        self.below=receive(self.patient,self.visit,'repeat-vitals','Heart rate: 89 bpm.\nRespiratory rate: 19/min.',self.stamp)
        self.study=read_json(R11/'compiled.json')['rules']['186']['source']['trial_id']

    def call(self, items, criterion=None, extra=()):
        with TemporaryDirectory() as d:
            f=Path(d)/'bundle.json'
            f.write_text(json.dumps(dict(resourceType='Bundle',type='collection',entry=[{'resource':r} for r in items])))
            args=[sys.executable,'-B',str(R11.parents[1]/'pocketmd.py'),'fhir-screen',
                  '--bundle',str(f),'--subject','Patient/'+self.patient,'--study',self.study,
                  '--encounter','Encounter/'+self.visit]
            if criterion: args+=['--criterion',criterion]
            return subprocess.run(args+list(extra),text=True,capture_output=True)

    def test_arrival_and_actual_source_ids(self):
        r=self.call(self.base)
        self.assertEqual(r.returncode,0,r.stderr)
        baseline=json.loads(r.stdout)['criteria']
        self.assertEqual([baseline[k]['state'] for k in ('186','187')],['MISSING_DATA']*2)
        # Hospital IDs may differ from the intake's deterministic IDs.
        data=deepcopy(self.at)
        renames={}
        for i,x in enumerate(r for r in data if r['resourceType']=='Observation'):
            new='vital-'+str(i)
            renames['Observation/'+x['id']]='Observation/'+new
            x['id']=new
            x['encounter']={'reference':'Encounter/'+self.visit}
        for p in (r for r in data if r['resourceType']=='Provenance'):
            p['target'][0]['reference']=renames[p['target'][0]['reference']]
        r=self.call(self.base+data)
        self.assertEqual(r.returncode,0,r.stderr)
        rows=json.loads(r.stdout)['criteria']
        for k,line in [('186',0),('187',1)]:
            row=rows[k]
            self.assertEqual(row['state'],'MET')
            source=row['evidence'][0]
            self.assertIn(source,renames.values())
            self.assertEqual(row['locations'][source]['document'],'DocumentReference/vitals-sheet')
            self.assertEqual(row['locations'][source]['lines'],[line])
            self.assertEqual(len(row['locations'][source]['sha256']),64)
        single=self.call(self.base+data,'187')
        self.assertEqual(set(json.loads(single.stdout)['criteria']),{'187'})

    def test_wrong_visit_conflicts_and_missing_provenance(self):
        wrong=receive(self.patient,'visit-b','prior-vitals','Heart rate: 140 bpm.\nRespiratory rate: 29/min.',self.stamp)
        other=receive('another-patient','visit-c','their-vitals','Heart rate: 140 bpm.',self.stamp)
        for case in (self.base+wrong,self.base+other,self.base+self.at+self.below,
                     self.base+[r for r in self.at if r['resourceType']!='Provenance']):
            with self.subTest(resources=len(case)):
                result=self.call(case,'186')
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(json.loads(result.stdout)['criteria']['186']['state'],'MISSING_DATA')
        invalid=[dict(r,status='entered-in-error') if r['resourceType']=='Encounter' else r for r in self.base+self.at]
        self.assertIn('Encounter is invalid',self.call(invalid,'186').stderr)
        for mutation,message in [('value','Value or provenance'),('encounter','different encounter'),('source','Invalid source digest')]:
            data=deepcopy(self.at)
            obs=next(r for r in data if r['resourceType']=='Observation')
            doc=next(r for r in data if r['resourceType']=='DocumentReference')
            if mutation=='value': obs['valueQuantity']['value']=150
            elif mutation=='encounter': obs['encounter']={'reference':'Encounter/other'}
            else: doc['identifier'][0]['value']='f'*64
            result=self.call(self.base+data,'186')
            self.assertNotEqual(result.returncode,0)
            self.assertIn(message,result.stderr)
            self.assertFalse(result.stdout)

    def test_reject_unsupported_composition(self):
        result=self.call(self.base,'186',('--review-answer','a','--review-trust','t',
                              '--governing-protocol','p','--as-of','2026-01-01'))
        self.assertNotEqual(result.returncode,0)
        self.assertIn('single-document',result.stderr)
        self.assertFalse(result.stdout)

if __name__=='__main__': unittest.main()
