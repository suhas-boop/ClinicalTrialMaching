import json,unittest
from registry_context import packet
from review_vignette_case import review_case

class SourceTests(unittest.TestCase):
    def test_registry_fingerprint_and_study(self):
        raw=json.dumps({'protocolSection':{'identificationModule':{'nctId':'NCT00000001'},'eligibilityModule':{'eligibilityCriteria':'Adults only.'}}}).encode()
        self.assertTrue(packet('NCT00000001','Adults only.',raw)['criterion_in_eligibility_text'])
        self.assertFalse(packet('NCT00000001','Children.',raw)['criterion_in_eligibility_text'])
        with self.assertRaises(ValueError):packet('NCT00000002','Adults only.',raw)
    def test_single_subject_request_and_independent_protocol_question(self):
        fact={'scope':'age years','role':'record','label':'age_years','kind':'number','unit':'a'}
        rule={'expression':{'fact':'age_years','op':'ge','value':18},'facts':{'age_years':fact}}
        entry={'study':'Example','id':'A','rule':rule,'criterion_text':'Age 18 or older'}
        hold=dict(entry,id='B',criterion_text='As defined above',rule={'facts':{},'expression':{'hold':'Supply cited definition.'}})
        case=review_case('x','0. A group of 14 patients presents today.',[entry,hold])
        self.assertEqual({v['state'] for v in case['criteria']['Example'].values()},{'SOURCE_SCOPE_HOLD'})
        self.assertEqual([v['route'] for v in case['requests']],['identify_subject','protocol_review'])
    def test_single_individual_receipt(self):
        spec={'scope':'age years','role':'record','label':'age_years','kind':'number','unit':'a'}
        entry={'study':'Example','id':'A','criterion_text':'Under 18','rule':{'facts':{'age_years':spec},'expression':{'fact':'age_years','op':'lt','value':18}}}
        r=review_case('x','0. A 25-year-old man presents to the clinic.',[entry])
        self.assertEqual(r['criteria']['Example']['A']['state'],'NOT_MET')
        self.assertEqual(r['criteria']['Example']['A']['sentences'],[0])
