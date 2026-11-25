"""A synthetic 21-year minimum exercises the independently reviewed new-rule path."""
import hashlib
import json
import unittest
from pathlib import Path

from compiler import digest, screen
from extensions import compile_reviewed, evaluate_reviewed, _fixture

EXAMPLE = Path(__file__).parent / 'examples' / 'intake-age'


class ReviewedRuleTests(unittest.TestCase):
    def setUp(self):
        from intake_source import build_intake_packet
        manifest = json.loads((EXAMPLE/'manifest.json').read_text())
        self.packet = build_intake_packet(manifest, (EXAMPLE/'protocol.pdf').read_bytes(), [])
        self.draft = json.loads((EXAMPLE/'author.json').read_text())
        self.review = json.loads((EXAMPLE/'review.json').read_text())
        self.compiled = compile_reviewed(self.packet, self.draft, self.review)

    def test_transfer_and_execute_nondefault_threshold(self):
        self.assertEqual(self.compiled['state'], 'READY', self.compiled['reason'])
        self.assertEqual([x['actual'] for x in self.compiled['controls']], ['MET', 'MET', 'NOT_MET', 'MISSING_DATA'])
        b = _fixture(self.packet['study'], '2026-11-20', '2005-11-21')
        result = evaluate_reviewed(self.compiled, b, 'fixture', 'screen', '2026-11-20T12:00:00Z')
        self.assertEqual(result['state'], 'NOT_MET')
        self.assertIn('Patient/fixture/_history/1', result['evidence'])
        self.assertEqual(evaluate_reviewed(self.compiled,b,'other','screen','2026-11-20T12:00:00Z')['state'],'MISSING_DATA')

    def test_new_feedback_invalidates_approval(self):
        self.packet['answers'].append({'answer':'New interpretation'})
        self.assertEqual(compile_reviewed(self.packet,self.draft,self.review)['state'],'VALIDATION_HOLD')

    def test_identity_threshold_and_fixtures_locked(self):
        for k,v in [('criterion_id','other'),('authority',''),('reference_rule',{'fact':'age','operator':'ge','threshold':18}),
                    ('reviewer_type','model'),('covered_obligation_ids',[]),('control_cases',[]),('draft_sha256','')]:
            with self.subTest(k=k):
                self.assertEqual(compile_reviewed(self.packet,self.draft,{**self.review,k:v})['state'],'VALIDATION_HOLD')

    def test_changed_controls_are_verified(self):
        self.review['control_cases'][1]['birth_date']='2001-11-20'
        self.assertIn('exact qualifying birthday',compile_reviewed(self.packet,self.draft,self.review)['reason'])

    def test_edits_do_not_bypass_promotion(self):
        self.compiled['executable']['operator']='le'
        b = _fixture(self.packet['study'],'2026-11-20','2000-11-20')
        self.assertEqual(evaluate_reviewed(self.compiled,b,'fixture','screen','2026-11-20T12:00:00Z')['state'],'VALIDATION_HOLD')
        self.draft['clinical_questions']=[{'question':'Which date?'}]
        self.review['draft_sha256']=digest(self.draft)
        self.assertEqual(compile_reviewed(self.packet,self.draft,self.review)['state'],'VALIDATION_HOLD')

    def test_fixture_cannot_impersonate_existing_study(self):
        self.packet['study']='106S01'
        self.assertEqual(compile_reviewed(self.packet,self.draft,self.review)['state'],'VALIDATION_HOLD')

    def test_forged_binding_rejected(self):
        next(m for m in self.packet['catalog']['mappings'] if m['key']=='age')['value']='Patient.id'
        self.assertEqual(compile_reviewed(self.packet,self.draft,self.review)['state'],'VALIDATION_HOLD')

    def test_altered_uploaded_bytes_cannot_use_fictional_reference(self):
        from intake_source import build_intake_packet
        pdf = (EXAMPLE/'protocol.pdf').read_bytes() + b'\n% Alternate protocol revision\n'
        manifest = dict(self.packet['intake_manifest'], protocol_sha256=hashlib.sha256(pdf).hexdigest())
        packet = build_intake_packet(manifest,pdf,[])
        self.draft['protocol_sha256'] = manifest['protocol_sha256']
        self.review.update(protocol_sha256=manifest['protocol_sha256'], draft_sha256=digest(self.draft))
        outcome = compile_reviewed(packet,self.draft,self.review)
        self.assertEqual(outcome['state'],'VALIDATION_HOLD')
        self.assertIn('exact shipped synthetic',outcome['reason'])

    def test_fictional_reference_cannot_approve_real_mode(self):
        from intake_source import build_intake_packet
        manifest = dict(self.packet['intake_manifest'], synthetic_fixture=False)
        packet = build_intake_packet(manifest,(EXAMPLE/'protocol.pdf').read_bytes(),[])
        self.assertEqual(compile_reviewed(packet,self.draft,self.review)['state'],'VALIDATION_HOLD')

    def test_reference_replay_requires_intact_uploaded_source(self):
        proof = self.compiled['promotion_proof']
        proof['packet']['protocol_attachment']['data_base64'] = 'AAAA'
        self.compiled['review_sha256'] = digest(proof)
        result = evaluate_reviewed(self.compiled,_fixture(self.packet['study'],'2026-11-20','1990-01-01'),
                                   'fixture','screen','2026-11-20T12:00:00Z')
        self.assertEqual(result['state'],'VALIDATION_HOLD')

    def test_complex_signed_criterion_cannot_use_fixture_receipt(self):
        row=next(x for x in screen.INVENTORY['criteria'] if x['id']=='REC-1245-101-I01')
        digest_id=screen.INVENTORY['studies'][row['study']]['protocol_sha256']
        self.packet.update(study=row['study'],criterion_id=row['id'],criterion_text=row['extracted_text'],protocol_sha256=digest_id)
        self.packet.pop('synthetic_fixture',None)
        self.packet.pop('source_mode',None)
        self.draft.update(study=row['study'],criterion_id=row['id'],protocol_sha256=digest_id)
        self.review.update(study=row['study'],criterion_id=row['id'],criterion_text=row['extracted_text'],protocol_sha256=digest_id,draft_sha256=digest(self.draft))
        self.assertEqual(compile_reviewed(self.packet,self.draft,self.review)['state'],'VALIDATION_HOLD')


if __name__ == '__main__':
    unittest.main()
