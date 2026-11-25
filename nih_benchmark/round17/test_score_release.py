"""Verify that scoring and ordinary FHIR screening agree on a controlled authority response."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
sys.path.insert(0, str(BENCH/'round16'))
import evidence_score
from review706 import clarify
# Only these controls can provision the ephemeral test authority.
sys.path.insert(0, str(BENCH/'round16/review706'))
import test_clarify

def fixture():
    obj = test_clarify.ProtocolTests()
    obj.setUp()
    return obj

class AgreementTests(unittest.TestCase):
    def test_all_assignments_pass_through_shared_matcher(self):
        answer=fixture()
        authority=dict(envelope=answer.sign(), trust=answer.trust, protocol_bytes=answer.proto, as_of=answer.asof)
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)
            result=evidence_score.run(out,authority)
            self.assertEqual(result['assignments'],134)
            receipt=json.loads((out/'definitive_evidence.json').read_text())
            self.assertEqual(len(receipt),7)
            self.assertTrue(all(x['references'] and x['cited_lines'] for x in receipt.values()))
            self.assertEqual(result['reference_definite'],91)
            self.assertEqual(result['changed_by_authority'],[clarify.CASE])
            self.assertEqual(result['original_strict']['agreeing_definite'],6)
            self.assertEqual(result['with_actual_authority']['agreeing_definite'],7)
            trace=json.loads((out/'actual_authority_result.json').read_text())
            decision=trace['criteria'][clarify.CASE]
            self.assertTrue(decision['evidence'])
            self.assertEqual(decision['source_sentences'],[0])
            self.assertNotEqual(trace['base_catalog_sha256'],trace['catalog_sha256'])
            for ref in decision['evidence']:
                self.assertIn(ref,decision['source_spans'])
            answer.trust['revoked'].append('simulation')
            with self.assertRaises(ValueError):
                evidence_score.run(out/'revoked',authority)
            self.assertFalse((out/'revoked'/'score.json').exists())

if __name__=='__main__':
    unittest.main()
