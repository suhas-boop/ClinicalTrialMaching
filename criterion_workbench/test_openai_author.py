"""Exercise the actual HTTP request builder and raw response parser without a live API call."""
from contextlib import closing
from io import BytesIO
import base64
import hashlib
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import openai_author as provider


def completed(text, extra=()):
    return {"status":"completed","output":[*extra,{"type":"message","role":"assistant",
            "status":"completed","content":[{"type":"output_text","text":text}]}]}


def packet(fmt="pdf"):
    raw = b"private source"
    return {"criterion_id":"private-criterion","study":"PRIVATE-STUDY","protocol_sha256":hashlib.sha256(raw).hexdigest(),
            "criterion_text":"PRIVATE criterion","section":"g","polarity":"inclusion","catalog_version":"1",
            "catalog":{"mappings":[]},"source":{"version":"1"},"answers":[{"answer":"Private clarification"}],
            "protocol_attachment":{"format":fmt,"data_base64":base64.b64encode(raw).decode()},
            "protocol_context":{"text":"[AA123456] Private paragraph"},"patient_bundle":"MUST-NOT-SEND"}


class ResponsesTests(unittest.TestCase):
    def test_original_pdf_no_search_no_patient_and_raw_output(self):
        seen = []
        class Capture:
            def open(self, req, timeout):
                seen.append(req)
                return closing(BytesIO(json.dumps(completed(' {"x": 1}\n')).encode()))
        with patch.object(provider,"build_opener",return_value=Capture()):
            self.assertEqual(provider.author_packet(packet(),"model","example-key"),' {"x": 1}\n')
        body=json.loads(seen[0].data)
        self.assertEqual(seen[0].full_url,"https://api.openai.com/v1/responses")
        self.assertEqual(seen[0].get_header("Authorization"),"Bearer example-key")
        self.assertEqual(body["input"][0]["content"][0]["file_data"],"data:application/pdf;base64,cHJpdmF0ZSBzb3VyY2U=")
        self.assertNotIn("tools",body)
        self.assertFalse(body["store"])
        self.assertNotIn("MUST-NOT-SEND",str(body))
        self.assertIn("Private clarification",str(body))

    def test_public_lookup_isolated_retrieved_sources_only(self):
        url="https://evs.nci.nih.gov/fixture"
        row={"term":"PD","code":"x","version":"v","system":"NCIt","url":url}
        lookup=completed(json.dumps({"candidates":[row]}),[{"type":"web_search_call","status":"completed",
                         "action":{"sources":[{"url":url}]}}])
        with patch.object(provider,"_send",side_effect=[lookup,completed("{}")]) as send:
            self.assertEqual(provider.author_packet(packet("docx"),"m","k",["response"]),"{}")
        public,private=[c.args[0] for c in send.call_args_list]
        self.assertNotIn("PRIVATE",str(public));self.assertNotIn("Private",str(public))
        self.assertIn("allowed_domains",public["tools"][0]["filters"])
        self.assertIn("[AA123456]",str(private));self.assertIn(url,str(private));self.assertNotIn("tools",private)
        bad=completed(json.dumps({"candidates":[{**row,"url":"https://example.com"}]}),lookup["output"][:1])
        with patch.object(provider,"_send",return_value=bad) as send,self.assertRaisesRegex(provider.ProviderError,"unverifiable"):
            provider.author_packet(packet(),"m","k",["response"])
        self.assertEqual(send.call_count,1)

    def test_config_malformed_response_partial_and_refusal(self):
        with patch.object(provider,"_send") as send:
            with self.assertRaisesRegex(ValueError,"OPENAI_API_KEY"):provider.author_packet(packet(),"m",None)
            with self.assertRaisesRegex(ValueError,"OPENAI_MODEL"):provider.author_packet(packet(),"","k")
            send.assert_not_called()
        partial=completed('{"part":')
        partial["status"]="incomplete"
        with patch.object(provider,"_send",return_value=partial),self.assertRaises(provider.ProviderError) as raised:
            provider.author_packet(packet(),"m","k")
        self.assertEqual(raised.exception.partial,'{"part":')
        refusal=completed("")
        refusal["output"][0]["content"]=[{"type":"refusal","refusal":"refused"}]
        with patch.object(provider,"_send",return_value=refusal),self.assertRaises(provider.ProviderError) as raised:
            provider.author_packet(packet(),"m","k")
        self.assertEqual(raised.exception.partial,"refused")

    def test_http_failure_drops_headers_and_redacts_key_without_retry(self):
        key="sk-private-example"
        body=json.dumps({"error":{"type":"bad_request","code":"test","param":"model","message":"error "+key}}).encode()
        exception=HTTPError(provider.ENDPOINT,400,"Bad Request",{"Authorization":"another secret header"},BytesIO(body))
        with patch.object(provider,"build_opener") as opener:
            opener.return_value.open.side_effect=exception
            with self.assertRaises(provider.ProviderError) as error:provider.author_packet(packet(),"m",key)
            self.assertEqual(opener.return_value.open.call_count,1)
        self.assertIn("HTTP 400",str(error.exception));self.assertIn("bad_request",str(error.exception))
        self.assertNotIn(key,str(error.exception));self.assertNotIn("another secret",str(error.exception))


if __name__ == "__main__":
    unittest.main()
