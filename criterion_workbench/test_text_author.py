import copy
import os
import sys
import unittest
from unittest.mock import patch

from bounded_rules import approved_catalog
from text_author import make_provider, propose


class TextAuthorTests(unittest.TestCase):
    def setUp(self):
        self.sources = {"criterion": "Participants require a screening ECOG of 0 or 1."}
        self.catalog = approved_catalog()
        self.expr = {"fact": "ecog", "op": "in", "values": [0, 1]}
        self.cite = {"source_id": "criterion", "quote": self.sources["criterion"]}
        self.candidate = {"status": "EXECUTABLE", "expression": self.expr, "questions": [],
                          "gaps": [], "citations": [self.cite], "reason": "Requires a score of 0 or 1."}
        self.verifier = {"verdict": "PASS", "questions": [], "gaps": [],
                         "obligations": [dict(self.cite, coverage="REPRESENTED",
                         detail="The screening ECOG score uses the stated two-member set.")],
                         "reason": "The comparison preserves all stated conditions."}

    def proposal(self):
        self.calls = []

        def provider(task, packet):
            self.calls.append((task, packet))
            return copy.deepcopy(self.candidate if task == "author" else self.verifier)

        return propose(self.sources, self.catalog, provider)

    def test_separate_calls_gate_an_executable(self):
        result = self.proposal()
        self.assertEqual("EXECUTABLE", result["status"])
        self.assertEqual([("author", False), ("verify", True)],
                         [(k, "candidate" in v) for k, v in self.calls])
        self.assertEqual(["ecog"], result["audit"]["bound_facts"])
        self.assertEqual(self.verifier, result["audit"]["verification"])

    def test_unverifiable_quote_is_withheld_before_verifier(self):
        self.candidate["citations"] = [{"source_id":"criterion", "quote":"screening ECOG of 0 or 2"}]
        self.assertEqual("VALIDATION_REVIEW", self.proposal()["status"])
        self.assertEqual(1, len(self.calls))

    def test_approval_cannot_override_missing_binding(self):
        self.catalog = approved_catalog(keys=["age"])
        self.assertIsNone(self.proposal()["expression"])

    def test_true_model_disagreement_does_not_release(self):
        self.verifier.update(verdict="VALIDATION_REVIEW", reason="The threshold differs from the source.")
        self.assertEqual("VALIDATION_REVIEW", self.proposal()["status"])

    def test_each_source_is_reviewed(self):
        for key in ("protocol", "polarity"):
            with self.subTest(key=key):
                self.sources[key] = "source section"
                self.assertEqual("VALIDATION_REVIEW", self.proposal()["status"])
                del self.sources[key]

    def test_answers_go_back_into_both_requests(self):
        self.sources.update({"question:Q1":"Which screening score qualifies?",
                             "answer:Q1":"The permitted screening scores are 0 or 1."})
        self.assertEqual("VALIDATION_REVIEW", self.proposal()["status"])
        anscite = {"source_id":"answer:Q1", "quote":self.sources["answer:Q1"]}
        self.verifier["obligations"].append(dict(anscite, coverage="REPRESENTED",
                                                  detail="Confirmed the allowed two scores."))
        self.assertEqual("VALIDATION_REVIEW", self.proposal()["status"])
        self.candidate["citations"].append(anscite)
        self.assertEqual("EXECUTABLE", self.proposal()["status"])
        for _, packet in self.calls:
            self.assertEqual(self.sources, packet["sources"])

    def test_question_itself_is_never_evidence(self):
        self.sources["question:Q1"] = "Can a score of 2 qualify?"
        self.candidate["citations"].append({"source_id":"question:Q1", "quote":"2"})
        self.assertEqual("VALIDATION_REVIEW", self.proposal()["status"])

    def test_verifier_can_cite_question_only_as_context(self):
        self.sources["question:Q1"] = "Can a score of 2 qualify?"
        row = {"source_id":"question:Q1", "quote":self.sources["question:Q1"],
               "coverage":"CONTEXT", "detail":"The question is background; the number is not evidence."}
        self.verifier["obligations"].append(row)
        self.assertEqual("EXECUTABLE", self.proposal()["status"])
        row["coverage"] = "REPRESENTED"
        self.assertEqual("VALIDATION_REVIEW", self.proposal()["status"])
        row.update(coverage="CONTEXT", quote="a score of 4")
        self.assertEqual("VALIDATION_REVIEW", self.proposal()["status"])

    def test_ambiguous_target_is_a_focused_clinical_question(self):
        self.sources["criterion"] = "A qualifying screening ECOG is required."
        self.cite["quote"] = self.sources["criterion"]
        question = "Which screening ECOG scores qualify?"
        self.candidate.update(status="INVESTIGATOR_REVIEW", expression=None, questions=[question])
        self.verifier["obligations"] = [dict(self.cite, coverage="QUESTION", detail="Threshold is missing.")]
        out = self.proposal()
        self.assertEqual("INVESTIGATOR_REVIEW", out["status"])
        self.assertEqual([question], out["questions"])
        self.assertIsNone(out["expression"])

    def test_exclusion_draft_inversion_remains_held_on_verifier_objection(self):
        self.sources = {"criterion":"Exclude participants with screening ECOG greater than 1.",
                        "polarity":"exclusion"}
        self.candidate["expression"] = {"fact":"ecog", "op":"gt", "value":1}
        self.candidate["citations"] = [{"source_id":k, "quote":v} for k,v in self.sources.items()]
        self.verifier.update(verdict="VALIDATION_REVIEW", reason="Expression is true for an excluded patient.",
                             obligations=[dict(c, coverage="CONTEXT", detail="Author must invert this finding.")
                                          for c in self.candidate["citations"]])
        self.assertIsNone(self.proposal()["expression"])
        self.candidate["expression"]["op"] = "le"
        self.verifier.update(verdict="PASS", reason="The expression is true when the exclusion is clear.")
        for r in self.verifier["obligations"]:
            r.update(coverage="REPRESENTED", detail="ECOG <= 1 clears the stated exclusion at screening.")
        self.assertEqual("EXECUTABLE", self.proposal()["status"])

    def test_conflicting_investigator_answer_can_return_to_review(self):
        self.sources.update({"question:Q1":"Which scores qualify?", "answer:Q1":"Allow a score of 2 as well."})
        self.candidate["expression"]["values"].append(2)
        self.candidate["citations"].append({"source_id":"answer:Q1", "quote": self.sources["answer:Q1"]})
        self.verifier.update(verdict="INVESTIGATOR_REVIEW",
                             questions=["Is there a formal amendment authorizing score 2?"],
                             obligations=[dict(c, coverage="QUESTION", detail="Answer conflicts with protocol.")
                                          for c in self.candidate["citations"]])
        result = self.proposal()
        self.assertEqual("INVESTIGATOR_REVIEW", result["status"])
        self.assertIsNone(result["expression"])

    def test_clinical_opinion_needs_patient_level_contract(self):
        self.sources["criterion"] = "For each patient obtain the investigator's prognosis."
        self.cite["quote"] = self.sources["criterion"]
        self.candidate.update(status="INVESTIGATOR_REVIEW", expression=None,
                              questions=["What is the first patient's prognosis?"])
        gap = "Add a dated, investigator-attributed prognosis binding for each patient."
        self.verifier.update(verdict="BINDING_REVIEW", gaps=[gap],
                             obligations=[dict(self.cite, coverage="GAP", detail=gap)])
        out = self.proposal()
        self.assertEqual("BINDING_REVIEW", out["status"])
        self.assertEqual([], out["questions"])
        self.assertEqual([gap], out["gaps"])

    def test_verifier_cannot_pass_uncovered_branch(self):
        self.verifier["obligations"][0]["coverage"] = "GAP"
        self.assertIsNone(self.proposal()["expression"])

    def test_malformed_verifier_returns_validation_hold(self):
        self.verifier["verdict"] = []
        self.assertEqual("VALIDATION_REVIEW", self.proposal()["status"])

    def test_retryable_transport_failure_propagates(self):
        def provider(task, packet):
            raise RuntimeError("model unavailable")
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            propose(self.sources, self.catalog, provider)

    def test_command_transport_json_contract(self):
        script = ("import json,sys; d=json.load(sys.stdin); "
                  "print(json.dumps({'task':d['task'], 'source':d['packet']['sources']['criterion'],"
                  "'instructed': 'formal amendment' in d['instructions']}))")
        provider = make_provider(None, [sys.executable, "-c", script])
        self.assertEqual({"task":"verify", "source":self.sources["criterion"], "instructed":True},
                         provider("verify", {"sources": self.sources}))

    def test_command_failure_never_includes_stderr(self):
        provider = make_provider(None, [sys.executable, "-c",
                                       "import sys;sys.stderr.write('private source copy');sys.exit(1)"])
        with self.assertRaisesRegex(RuntimeError, "^Model command failed with exit code 1"):
            provider("author", {})

    def test_live_transport_sets_store_false_and_requests_json(self):
        key = "test-only"
        fake = {"output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"{}"}]}],
                "status":"completed"}
        with patch.dict(os.environ, {"OPENAI_API_KEY":key}), patch("openai_author._send", return_value=fake) as send:
            out = make_provider("configured-model")("author", {"sources": self.sources})
        self.assertEqual({}, out)
        body, sent_key = send.call_args.args
        self.assertEqual(key, sent_key)
        self.assertIs(body["store"], False)
        self.assertEqual({"format":{"type":"json_object"}}, body["text"])
        self.assertIn("polarity", body["instructions"])
        self.assertIn("JSON", body["input"])
        self.assertIn(self.sources["criterion"], body["input"])

    def test_missing_key_fails_before_attempt(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            make_provider("test-model")

    def test_command_duplicate_keys_are_rejected(self):
        provider = make_provider(None, [sys.executable, "-c", """print('{"k":1,"k":2}')"""])
        with self.assertRaisesRegex(RuntimeError, "usable JSON"):
            provider("author", {})


if __name__ == "__main__":
    unittest.main()
