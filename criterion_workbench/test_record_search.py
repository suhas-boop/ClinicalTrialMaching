import base64
from copy import deepcopy
import json
from pathlib import Path
import unittest

from record_search import add_document, chart_export, connect, import_bundle, record_family, retrieve, search
from bindings import make_packet
from test_recover_records import example, V, AT, EARLY

class DocumentFamilyRouting(unittest.TestCase):
    def test_evidence_target_precedes_treatment_context(self):
        scopes = {
            "unable to travel for treatment or followup": "screening logistics or social work record",
            "prior neck irradiation": "radiation treatment record",
            "prior radioactive iodine therapy": "nuclear medicine treatment record",
            "continuous days of administered voriconazole and caspofungin for invasive aspergillosis":
                "prior medication and administration record",
            "can retain oral medication": "clinical or historical assessment",
            "unable to swallow oral drug": "clinical or historical assessment",
            "drug hypersensitivity to an antifungal drug": "allergy record",
            "head CT showed lung cancer": "imaging report",
            "failed MRI metal screen": "MRI safety screening record",
            "parasites per ml": "laboratory report",
            "penetrating abdominal trauma": "injury or emergency assessment",
            "laparotomy for abdominal trauma": "procedure or operative record",
            "breastfeeding": "reproductive history",
            "lifelong interest in treatment": "clinical or historical assessment",
            "": "clinical or historical assessment",
        }
        for scope, expected in scopes.items():
            with self.subTest(scope=scope):
                self.assertEqual(record_family(scope), expected)


class Retrieval(unittest.TestCase):
    def setUp(self):
        self.db=connect(':memory:')
        self.addCleanup(self.db.close)
        r=json.loads((Path(__file__).resolve().parents[1]/'nih_benchmark/round3/rules.json').read_text())
        self.rules={'186':r['186']}
        self.study='NCT01526382'
        self.packet=make_packet(self.rules,{},self.study,V,stamp=AT)
        self.sheet=dict(resourceType='DocumentReference',id='screen-vitals',meta=dict(versionId='1',lastUpdated=AT),
            subject=dict(reference='Patient/demo'),author=[dict(reference='Organization/demo-record')],status='current',
            docStatus='final',date=AT,type=dict(coding=[dict(system='urn:pocketmd:research:document-type:v1',code='screening-vitals')]),
            context=dict(encounter=[dict(reference='Encounter/screen')],related=[dict(reference='Condition/index-demo')],period=dict(start=AT,end=AT)))
    def sheet_result(self,body,*others):
        doc=dict(self.sheet,content=[{'attachment':{'contentType':'text/plain','data':base64.b64encode(body.encode()).decode()}}])
        import_bundle(self.db,dict(resourceType='Bundle',type='collection',entry=[{'resource':r} for r in [doc,*others]]))
        return retrieve(self.db,self.rules,self.packet,self.study,V)['after']['186']
    def test_numeric_threshold(self):
        out=self.sheet_result('HR 90 bpm')
        self.assertEqual(out['state'],'MET')
        self.assertIn('DocumentReference/screen-vitals/_history/1#attachment=1&line=1',out['evidence'])
    def test_below_threshold(self):
        self.assertEqual(self.sheet_result('HR 89 bpm')['state'],'NOT_MET')
    def test_incomplete(self):
        self.assertEqual(self.sheet_result('tachycardic')['state'],'MISSING_DATA')
    def test_relative(self):
        self.assertEqual(self.sheet_result("Father's measurements\nHR 110 bpm")['state'],'MISSING_DATA')
    def test_inconsistent(self):
        self.assertEqual(self.sheet_result('HR 89 bpm\nHR 100 bpm')['state'],'MISSING_DATA')
    def test_wrong_visit(self):
        self.sheet['context']['encounter']=[{'reference':'Encounter/other'}]
        self.assertEqual(self.sheet_result('HR 101 bpm')['state'],'MISSING_DATA')
    def test_prior_measurement(self):
        self.sheet['context']['period']['start']=EARLY
        self.assertEqual(self.sheet_result('HR 101 bpm')['state'],'MISSING_DATA')
    def test_wrong_author(self):
        self.sheet['author']=[{'reference':'Practitioner/other'}]
        self.assertEqual(self.sheet_result('HR 101 bpm')['state'],'MISSING_DATA')
    def test_normalized_and_native_conflict(self):
        self.packet=make_packet(self.rules,{'186':{'heart_rate':60}},self.study,V,stamp=AT)
        self.assertEqual(self.sheet_result('HR 101 bpm')['state'],'MISSING_DATA')
    def test_chart_replay_and_withdrawal(self):
        rules,p,archive=example()
        def state():return retrieve(self.db,rules,p,'NCT02512159',V)['after']['116']['state']
        self.assertEqual(state(),'MISSING_DATA')
        self.assertEqual(import_bundle(self.db,archive),2)
        self.assertEqual(import_bundle(self.db,archive),0)
        self.assertEqual(state(),'NOT_MET')
        doc=deepcopy(archive['entry'][0]['resource']);doc['meta'].update(versionId='2',lastUpdated=AT)
        doc['status']='entered-in-error'
        import_bundle(self.db,dict(archive,entry=[{'resource':doc}]))
        self.assertEqual(state(),'MISSING_DATA')
    def test_research_passages_cannot_decide(self):
        add_document(self.db,'Patient/demo','public','1',EARLY,'case text',[('1','Heart rate 120 bpm')],[])
        out=retrieve(self.db,self.rules,self.packet,self.study,V)
        self.assertTrue(out['lookups'][0]['passages'])
        self.assertEqual(out['after']['186']['state'],'MISSING_DATA')
    def test_scope_and_asof(self):
        def put(p,k,v,t,**kw):add_document(self.db,'Patient/'+p,k,v,t,'report',[('line','tachycardic')],[],**kw)
        def lookup(t):return [r['source'] for r in search(self.db,'Patient/demo',t,'heart rate',encounter='Encounter/screen',episode='Condition/index-demo')]
        put('demo','first','1',EARLY);put('demo','first','2',AT,status='withheld')
        put('other','else','1',EARLY);put('demo','visit','1',EARLY,encounter='Encounter/other')
        put('demo','other-episode','1',EARLY,episode='Condition/other')
        self.assertEqual(lookup(EARLY),['first'])
        self.assertEqual(lookup(AT),[])
    def test_identity_conflict(self):
        args=['Patient/demo','a','1',EARLY,'report',[('1','one')],[]]
        add_document(self.db,*args);add_document(self.db,*args)
        args[-2]=[('1','two')]
        with self.assertRaises(ValueError):add_document(self.db,*args)
    def test_wrong_chart_link(self):
        data={'emr_patients':[{'clinic_id':'c','case_id':'x','fhir_id':'one'}],
            'emr_chart_records':[{'clinic_id':'c','case_id':'x','payload':{'resourceType':'DiagnosticReport','id':'d','subject':{'reference':'Patient/two'}}}],
            'emr_chart_documents':[{'clinic_id':'c','case_id':'x','source_refs':['DiagnosticReport/d']}]}
        with self.assertRaisesRegex(ValueError,'source link'):chart_export(self.db,data)

class OriginalAttachments(unittest.TestCase):
    def test_verified_attachment_arrival_and_redelivery(self):
        from tempfile import TemporaryDirectory
        import hashlib
        body=b'Chart text\nPulse 91 bpm'
        pin=hashlib.sha256(body).hexdigest()
        data={'emr_patients':[{'clinic_id':'c','case_id':'x','fhir_id':'demo'}],
              'emr_chart_records':[{'clinic_id':'c','case_id':'x','payload':{'resourceType':'DiagnosticReport',
                    'id':'d','subject':{'reference':'Patient/demo'},'status':'final'}}],
              'emr_chart_documents':[{'id':'doc','clinic_id':'c','case_id':'x','source_refs':['DiagnosticReport/d'],
                'updated_at':EARLY,'text_status':'none','text':[], 'category':'note','document_date':'2025-03-01',
                'content_type':'text/plain','sha256':pin}]}
        db=connect(':memory:');self.addCleanup(db.close)
        missing=[]
        chart_export(db,data,missing=missing)
        self.assertEqual([m['sha256'] for m in missing],[pin])
        with TemporaryDirectory() as root:
            file=Path(root)/pin;file.write_bytes(b'unrelated file')
            with self.assertRaisesRegex(ValueError,'digest'):chart_export(db,data,attachments=root,available_at=AT)
            file.write_bytes(body)
            self.assertEqual(chart_export(db,data,attachments=root,available_at=AT),{'hydrated':1})
            self.assertEqual(chart_export(db,data,missing=[]),{'already_hydrated':1})
        self.assertEqual(search(db,'Patient/demo',EARLY,'pulse'),[])
        hit=search(db,'Patient/demo',AT,'pulse')[0]
        self.assertEqual((hit['locator'],hit['links']),('page 1 line 2',['DiagnosticReport/d']))

    def test_pdf_text(self):
        import hashlib,io
        from tempfile import TemporaryDirectory
        try:
            from pypdf import PdfWriter
            from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
        except ImportError:
            self.skipTest('Optional PDF parser required for this test')
        from record_search import attachment_pages
        writer=PdfWriter()
        page=writer.add_blank_page(width=200,height=200)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),
                               NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
        stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 10 50 Td (Example record) Tj ET')
        page[NameObject('/Contents')]=writer._add_object(stream)
        buf=io.BytesIO();writer.write(buf);raw=buf.getvalue()
        with TemporaryDirectory() as d:
            f=Path(d)/'doc';f.write_bytes(raw)
            self.assertIn('Example record',attachment_pages(f,hashlib.sha256(raw).hexdigest(),'application/pdf')[0])

class LongitudinalSearch(unittest.TestCase):
    def test_prior_evidence_can_be_retrieved_from_earlier_visit(self):
        spec=dict(scope='prior antipsychotic exposure',role='record',kind='bool',label='Prior antipsychotic therapy')
        rules={'example':dict(facts={'prior_therapy':spec},expression={'fact':'prior_therapy'})}
        packet=make_packet(rules,{},'study',V,stamp=AT)
        db=connect(':memory:');self.addCleanup(db.close)
        add_document(db,'Patient/demo','older','1',EARLY,'prior medication list',[('line 1','Prior antipsychotic use')],[],
                     encounter='Encounter/earlier',episode='Condition/index-demo')
        result=retrieve(db,rules,packet,'study',V)
        self.assertEqual(result['lookups'][0]['passages'][0]['encounter'],'Encounter/earlier')
        self.assertEqual(result['after']['example']['state'],'MISSING_DATA')
