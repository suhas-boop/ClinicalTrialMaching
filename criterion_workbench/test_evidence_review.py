import unittest
from evidence_review import screen
from bindings import make_packet
from review_study import run
from screen_study import get_pack, ROOT, read

class ReviewTests(unittest.TestCase):
    def setUp(self):
        spec=dict(label='status',kind='bool',role='record',scope='Status documented in the narrative')
        self.rules={'one':{'facts':{'a':spec,'b':dict(spec,role='investigator',scope='Judgment from investigator')},
                           'expression':{'all':[{'fact':'a'},{'fact':'b'}]}}}
        self.rules['two']=self.rules['one']
    def apply(self,values,**kw):
        p=make_packet(self.rules,{'one':values},'demo','v1',**kw)
        return screen(self.rules,p,'demo','v1')
    def test_single_question_keeps_partial_evidence(self):
        out=self.apply({'a':True})
        self.assertEqual(len(out['requests']),1)
        self.assertEqual(out['requests'][0]['criteria'],['one','two'])
        self.assertEqual(out['requests'][0]['route'],'investigator')
        self.assertTrue(out['criteria']['one']['partial_evidence'])
    def test_signed_answer_resolves_and_removes_request(self):
        for answer,state in ((True,'MET'),(False,'NOT_MET')):
            out=self.apply({'a':True,'b':answer})
            self.assertEqual(out['criteria']['one']['state'],state)
            self.assertEqual(out['requests'],[])
    def test_duplicate_delivery_stable(self):
        p=make_packet(self.rules,{'one':{'a':True}},'demo','v1')
        first=screen(self.rules,p,'demo','v1')
        p['bundle']['entry']+=p['bundle']['entry'][-2:]
        self.assertEqual(first,screen(self.rules,p,'demo','v1'))
    def test_patient_separation(self):
        self.assertNotEqual(self.apply({'a':True})['requests'][0]['id'],
                            self.apply({'a':True},patient='different')['requests'][0]['id'])
    def test_no_patient_question_after_decisive_false(self):
        self.assertEqual(self.apply({'a':False})['requests'],[])
    def test_both_arms_postponed_until_conditional_gate(self):
        self.rules['one']['expression']={'if':{'fact':'a'},'then':{'fact':'b'},'else':True}
        out=self.apply({})
        self.assertEqual([r['route'] for r in out['requests']],['retrieve_record'])
    def test_sealed_example(self):
        p=read(ROOT/'examples/1479-0032-met.json')
        self.assertEqual(run(p)['review_mode'],'typed evidence review')
    def test_version_gate(self):
        p=make_packet(get_pack('PH-L19TNFDOX2')['rules'],{},'PH-L19TNFDOX2',
                      read(ROOT/'sources.json')['PH-L19TNFDOX2']['sha256'])
        self.assertEqual(run(p)['mode'],'historical_version_block')
