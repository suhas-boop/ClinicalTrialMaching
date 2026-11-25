from copy import deepcopy
import unittest
from term_policy import plain_chart, R11, verify, read_json, prescreen, REFERENCE
class TermPolicyTests(unittest.TestCase):
    base='A 40-year-old woman presents to the ER.\nOn examination she is tachypneic and tachycardic.'
    @classmethod
    def setUpClass(cls):cls.pack=verify(read_json(R11/'compiled.json'))
    def check(self,note,k='186',pack=None):
        b,_=plain_chart('test',note,'2026-11-24T00:00:00Z')
        pack=pack or self.pack
        return prescreen([e['resource'] for e in b['entry']],'Patient/test',pack,pack['rules'][k]['source']['trial_id'],k)
    def test_positive(self):
        for k in ['186','187']:
            a=self.check(self.base,k)
            self.assertEqual(a['criteria'][k]['state'],'MISSING_DATA')
            p=a['research_prescreen'];self.assertEqual(p['state'],'SUPPORTED_PENDING_MEASUREMENT');self.assertEqual(p['proof'][0]['reference'],REFERENCE)
            self.assertGreaterEqual(len(p['proof'][0]['resources']),2)
    def test_age_qualifier_subject_time(self):
        for note in [self.base.replace('40-year','16-year'),self.base.split('\n')[1],self.base.replace('she is','her mother is'),
                     self.base.replace('she is','she was'),self.base.replace('she is','she may be'),self.base.replace('she is','she is not'),
                     self.base+'\nShe is no longer tachycardic.']:
            self.assertEqual(self.check(note)['research_prescreen']['state'],'NO_ADDITIONAL_RESULT',note)
    def test_measurements(self):
        for qty,status in [('89','NOT_MET'),('90','MET')]:
            v=self.check(self.base+'\nHeart rate: '+qty+' bpm.')
            self.assertEqual(v['criteria']['186']['state'],status);self.assertFalse(v['research_prescreen']['proof'])
        v=self.check(self.base+'\nPulse was recorded as 82.')
        self.assertFalse(v['research_prescreen']['proof'])
        v=self.check(self.base+'\nHeart rate: 89 bpm.\nHeart rate: 91 bpm.')
        self.assertEqual(v['criteria']['186']['state'],'MISSING_DATA');self.assertFalse(v['research_prescreen']['proof'])
    def test_bounds(self):
        for op,num,support in [('gt',100,True),('ge',101,False),('gt',101,False),('le',100,False),('eq',100,False)]:
            p=deepcopy(self.pack);p['rules']['186']['rule']['expression'].update(op=op,value=num)
            self.assertEqual(bool(self.check(self.base,pack=p)['research_prescreen']['proof']),support)
if __name__=='__main__':unittest.main()
