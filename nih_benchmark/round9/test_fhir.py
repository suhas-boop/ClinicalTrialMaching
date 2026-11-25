from contextlib import closing
from copy import deepcopy
from pathlib import Path
import json,unittest,urllib.request,urllib.error,threading
from wsgiref.simple_server import make_server,WSGIRequestHandler
from convert import HERE,UNIT,LOINC,load,rid,build_case,review_table
from serve import app
from replay import VignetteChart
from chart import open_chart,search
class Quiet(WSGIRequestHandler):
    def log_message(self,*args):pass
class FhirChartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=make_server('127.0.0.1',0,app(HERE/'export/chart.sqlite'),handler_class=Quiet)
        cls.worker=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.worker.start()
        cls.base='http://127.0.0.1:'+str(cls.server.server_port)+'/fhir/'
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.worker.join()
    def get(self,path):
        with urllib.request.urlopen(self.base+path) as r:return json.load(r)
    def test_patient_and_group_inventory(self):
        self.assertEqual(self.get('Patient')['total'],52);self.assertEqual(self.get('Group')['total'],1)
        with self.assertRaises(urllib.error.HTTPError):self.get('Patient/sigir-201426')
    def test_heart_rate(self):
        url='Observation?patient=sigir-201418&code=http%3A%2F%2Floinc.org%7C8867-4'
        rows=self.get(url);self.assertEqual(rows['total'],1)
        r=rows['entry'][0]['resource'];self.assertEqual(r['valueQuantity']['value'],141);self.assertEqual(r['valueQuantity']['code'],'/min')
        self.assertEqual(self.get(r['derivedFrom'][0]['reference'])['subject']['reference'],'Patient/sigir-201418')
    def test_narrative_adjective_not_a_number(self):
        self.assertEqual(self.get('Observation?patient=sigir-201411&code=8867-4')['total'],0)
    def test_medication(self):
        r=self.get('MedicationStatement?patient=sigir-20147&medication=42351')['entry'][0]['resource']
        self.assertEqual(r['status'],'active')
        self.assertEqual(self.get('MedicationStatement?patient=sigir-201418&medication=42351')['total'],0)
    def test_relatives_not_patient_procedures(self):
        history=self.get('FamilyMemberHistory?patient=sigir-201427')
        self.assertEqual({e['resource']['relationship']['text'] for e in history['entry']},{'sister','brother'})
        self.assertNotIn('proctocolectomy',json.dumps(self.get('Procedure?patient=sigir-201427')))
    def test_time_and_repeat_values(self):
        b=self.get('Observation?patient=sigir-201514&code=718-7')
        self.assertEqual(sorted(e['resource']['valueQuantity']['value'] for e in b['entry']),[8.9,9.0])
        self.assertTrue(all('effectiveDateTime' not in e['resource'] for e in b['entry']))
    def test_roundtrip_idempotency(self):
        p='sigir-201418'
        b=load(HERE/'export/bundles'/(p+'.json'))
        rebuilt,_=build_case(p,load(HERE/'notes.json')[p],review_table()[p],load(HERE/'rxnorm.json'),load(HERE/'icd10cm.json'),load(HERE/'export/conversion.json')['recorded'])
        self.assertEqual(rebuilt,b)
    def test_corrupt_source_and_unit_rejected(self):
        subject='Patient/sigir-201418'
        with closing(open_chart(HERE/'export/chart.sqlite')) as db:resources=search(db,subject)
        doc=next(r for r in resources if r['resourceType']=='DocumentReference')
        old=doc['content'][0]['attachment']['data'];doc['content'][0]['attachment']['data']='dGVzdA=='
        with self.assertRaises(ValueError):VignetteChart(resources,subject)
        doc['content'][0]['attachment']['data']=old
        spec=dict(label='heart_rate',scope='heart rate',kind='number',role='record',unit='/min')
        self.assertEqual(VignetteChart(resources,subject).read(spec)[0],141)
        hr=next(r for r in resources if r.get('code',{}).get('text')=='heart rate')
        hr['valueQuantity']['code']='mg';self.assertEqual(VignetteChart(resources,subject).read(spec)[1],'MISSING_DATA')
    def test_no_unsupported_queries(self):
        with self.assertRaises(urllib.error.HTTPError) as err:self.get('Observation?birthdate=ignore')
        self.assertEqual(err.exception.code,400)
if __name__=='__main__':unittest.main()
