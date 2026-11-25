import base64
import hashlib
import json
from copy import deepcopy
from tempfile import TemporaryDirectory
from datetime import date
from pathlib import Path
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from clarify import *

class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.key=Ed25519PrivateKey.generate()
        self.proto=b'Synthetic protocol for authority validation controls, no clinical authorization.'
        digest=sha256(self.proto).hexdigest()
        self.asof=date(2026,11,24)
        self.trust={'authorities':{'synthetic':{'public_key':base64.b64encode(self.key.public_key().public_bytes_raw()).decode(),
            'scope':[[STUDY,CASE,'synthetic-1',digest]],'valid_from':'2026-01-01','valid_until':'2027-12-31',
            'active':True,'active_decision_id':'simulation'}},'revoked':[]}
        self.payload=dict(study=STUDY,criterion_id=CASE,registry_sha256=DIGEST,question_sha256=fingerprint(packet()),
            governing_protocol_sha256=digest,governing_version='synthetic-1',source_locator='Synthetic protocol control §1',
            authority_id='synthetic',decision_id='simulation',decision_date='2026-11-24',
            interpretation={k:v[0] for k,v in CHOICES.items()})
        self.bundle=frozen_bundle()
    def sign(self):
        return dict(payload=deepcopy(self.payload),signature=base64.b64encode(self.key.sign(canonical(self.payload))).decode())
    def run_case(self,**kwargs):
        return apply(kwargs.get('bundle',self.bundle),kwargs.get('patient',PATIENT),kwargs.get('envelope',self.sign()),
                     kwargs.get('trust',self.trust),kwargs.get('proto',self.proto),self.asof,kwargs.get('queue'))
    def test_frozen_and_alternative_meanings(self):
        self.assertEqual(self.run_case(envelope=None)['state'],'AUTHORING_HOLD')
        trace=self.run_case()
        self.assertEqual(trace['state'],'MET')
        self.assertEqual(trace['source_sha256'],read_json(BENCH/'round9/note_hashes.json')[PATIENT])
        text=read_json(BENCH/'round9/notes.json')[PATIENT]
        quotes={s['quote'] for s in trace['source_spans'].values()}
        self.assertEqual(quotes,{'woman','severe premenstrual and menstrual pelvic pain','heavy, irregular periods','occasional spotting between periods'})
        self.assertTrue(trace['evidence'])
        for ref in trace['evidence']:
            span=trace['source_spans'][ref]
            self.assertEqual(text[span['start']:span['end']],span['quote'])
        for op,diagnosis,state in [('ALL','symptoms_suffice','MISSING_DATA'),('ANY','also_require_separate_diagnosis','MISSING_DATA'),('ALL','also_require_separate_diagnosis','MISSING_DATA')]:
            self.payload['interpretation'].update(operator=op,requirement=diagnosis)
            self.assertEqual(self.run_case()['state'],state)
    def test_trust_scope_status_signature(self):
        self.assertRaises(ValueError,self.run_case,patient='wrong')
        self.assertRaises(ValueError,self.run_case,proto=b'altered')
        with self.subTest('key'):
            env=self.sign();env['signature']=base64.b64encode(b'z'*64).decode()
            self.assertRaises(ValueError,self.run_case,envelope=env)
        for name,bad in [('study','other'),('criterion_id','705'),('question_sha256','x'),('governing_version','2'),
                         ('registry_sha256','x'),('decision_date','2027-01-01'),('decision_id','old')]:
            orig=self.payload[name];self.payload[name]=bad
            with self.subTest(name=name): self.assertRaises(ValueError,self.run_case)
            self.payload[name]=orig
        self.trust['revoked'].append('simulation')
        self.assertRaises(ValueError,self.run_case)
    def test_negative_missing_conflict_other_subject(self):
        def score(text):
            b=plain_chart('qa',text,'2026-01-01T00:00:00Z')[0]
            return self.run_case(bundle=b,patient='qa')['state']
        reports='The patient is a woman.\nShe denies '+', '.join(s.replace('_',' ') for s in SYMPTOMS)+'.'
        self.assertEqual(score(reports),'NOT_MET')
        self.assertEqual(score('The patient is a woman.\nHer mother reports menorrhagia.'),'MISSING_DATA')
        self.assertEqual(score('The patient is a woman.\nShe reports menorrhagia.\nShe denies menorrhagia.'),'MISSING_DATA')
        self.assertEqual(score('The patient is a woman.\nShe reports menorrhagia.\nCorrection: current menorrhagia is uncertain.'),'MISSING_DATA')
        self.assertEqual(score('The patient is a woman.\nShe reports dyspareunia.'),'MET')
    def test_unhandled_and_persistence(self):
        with TemporaryDirectory() as tmp:
            queue=ReviewQueue(Path(tmp)/'review.sqlite')
            self.run_case(queue=queue)
            self.run_case(queue=queue)
            scope=dict(study=STUDY,criterion_id=CASE,protocol_sha256=self.payload['governing_protocol_sha256'])
            self.assertEqual(len(queue.answers(scope)),1)
        for key in CHOICES:
            old=self.payload['interpretation'][key]
            self.payload['interpretation'][key]='other_requires_followup'
            self.assertRaises(ValueError,self.run_case)
            self.payload['interpretation'][key]=old
if __name__=='__main__': unittest.main()
