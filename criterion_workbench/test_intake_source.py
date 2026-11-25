"""Checks for unindexed source intake, scoped answers and reconstructed compiler inputs."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
import unittest

import pymupdf

from intake_source import build_intake_packet, validated_row


class IntakeSourceTests(unittest.TestCase):
    def setUp(self):
        example = Path(__file__).resolve().parent / "examples/intake-age"
        self.manifest = json.loads((example / "manifest.json").read_bytes())
        self.raw = (example / "protocol.pdf").read_bytes()

    def packet(self, **changes):
        return build_intake_packet({**self.manifest, **changes}, self.raw, [])

    def test_uploaded_pdf_round_trip(self):
        p = self.packet()
        self.assertTrue(p["synthetic_fixture"])
        self.assertEqual(p["intake_manifest"], self.manifest)
        self.assertEqual(p["protocol_context"]["criterion_anchor"]["source_paragraph"], self.manifest["criterion_text"])
        self.assertEqual(validated_row(p)["pdf_pages"], [1, 1])
        self.assertIn("applied_question_ids", p["instructions"])

    def test_missing_source_corrupt_context_and_metadata(self):
        original = self.packet()
        for field, new in (("protocol_attachment", None), ("criterion_id", "another"),
                           ("protocol_context", {"text": self.manifest["criterion_text"]}),
                           ("catalog", {"version": "test-only"}), ("synthetic_fixture", 1)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validated_row({**original, field: new})

    def test_digest_page_text_and_reserved_scope(self):
        for key, val in (("protocol_sha256", "0"*64), ("pdf_page", 2), ("pdf_page", True),
                         ("criterion_text", "At screening, participants must be at least 18 years of age."),
                         ("study", "106s01"), ("criterion_id", "neok001-1-i02")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.packet(**{key:val})

    def test_exact_source_text_missing_marker_and_duplicate(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            for y in (100, 140):
                page.insert_text((80, y), self.manifest["criterion_text"])
            raw = pdf.tobytes()
        manifest = {**self.manifest, "protocol_sha256": hashlib.sha256(raw).hexdigest()}
        with self.assertRaisesRegex(ValueError, "marker"):
            build_intake_packet(manifest, raw, [])
        manifest["synthetic_fixture"] = False
        with self.assertRaisesRegex(ValueError, "found 2"):
            build_intake_packet(manifest, raw, [])

    def test_scoped_reviewer_answer(self):
        answer = {"question_id":"test","study":self.manifest["study"], "criterion_id":self.manifest["criterion_id"],
                  "protocol_sha256":self.manifest["protocol_sha256"], "authority":"QA fixture",
                  "decision_date":"2026-11-20", "source_reference":"synthetic reference",
                  "answer":"Calendar years", "question":"What age unit?"}
        packet = build_intake_packet(self.manifest, self.raw, [answer])
        self.assertEqual(packet["answers"][0]["answer"], "Calendar years")
        with self.assertRaises(ValueError):
            build_intake_packet(self.manifest, self.raw, [{**answer,"study":"other"}])


if __name__ == "__main__":
    unittest.main()
