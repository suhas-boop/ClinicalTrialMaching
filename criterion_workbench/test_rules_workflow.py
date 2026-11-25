"""Workflow and artifact integrity tests with deterministic, synthetic author responses."""
import copy
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import bounded_rules
import rules
from verify import N as STUDY, CUTOFF, box


AGE = {"fact":"age", "op":"ge", "value":18}
QUESTION = "What minimum age applies at screening?"
SECOND = "Is the age in completed years at screening?"
SCOPE = (STUDY, "research-v1", "I1")
TEXT = "Meet the protocol age requirement at screening."


def packets(queries=(), expr=AGE):
    def provider(task, packet):
        sources = packet["sources"]
        citations = [{"source_id":key, "quote":text} for key, text in sources.items() if not key.startswith("question:")]
        if task == "author":
            return {"status":"INVESTIGATOR_REVIEW" if queries else "EXECUTABLE",
                    "expression":None if queries else expr, "reason":"Synthetic test case.",
                    "citations":citations, "questions":list(queries), "gaps":[]}
        return {"verdict":"PASS", "reason":"Synthetic test review.", "questions":list(queries), "gaps":[],
                "obligations":[{**row, "coverage":"QUESTION" if queries else "REPRESENTED",
                                "detail":"Synthetic age predicate check."} for row in citations]}
    return provider


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = rules.RuleStore(self.temp.name)
        self.catalog = bounded_rules.approved_catalog(keys=["age"])

    def build(self, provider, text=TEXT, scope=SCOPE, **kw):
        return self.store.build(*scope, text, None, self.catalog, provider, **kw)

    def answer(self, provider, question="Q1", answer="At least 18 years old at screening."):
        return self.store.answer(*SCOPE, question, answer, "Synthetic reviewer", provider)

    def test_answer_reenters_author_and_verifier_and_exports(self):
        first = self.build(packets([QUESTION]))
        self.assertEqual([{"text":QUESTION, "id":"Q1"}], first["questions"])
        with self.assertRaises(ValueError):
            self.store.export(*SCOPE)
        provider = Mock(side_effect=packets())
        final = self.answer(provider)
        self.assertEqual("EXECUTABLE", final["status"])
        self.assertEqual(["author","verify"], [c.args[0] for c in provider.call_args_list])
        reopened = rules.RuleStore(self.temp.name)
        rule = reopened.export(*SCOPE)
        self.assertEqual("At least 18 years old at screening.", rule["sources"]["answer:Q1"])
        self.assertEqual("Synthetic reviewer", rule["answers"][0]["reviewer"])
        self.assertEqual(["age"], rule["bindings"])
        self.assertEqual("MET", rules.screen(rule, box(STUDY, "1990-01-01"), "demo", "screen", CUTOFF)["state"])
        self.assertNotIn("Patient/demo", json.dumps(rule))

    def test_incomplete_answer_creates_new_question(self):
        self.build(packets([QUESTION]))
        hold = self.answer(packets([QUESTION]), answer="Usual age.")
        self.assertEqual([{"id":"Q2","text":QUESTION}], hold["questions"])
        self.assertIsNone(hold["rule"])
        self.assertEqual("EXECUTABLE", self.answer(packets(), "Q2")["status"])

    def test_not_allowed_to_drop_sibling_questions(self):
        self.build(packets([QUESTION, SECOND]))
        result = self.answer(packets())
        self.assertEqual([{"id":"Q2","text":SECOND}], result["questions"])
        self.assertIsNone(result["rule"])
        self.assertEqual("INVESTIGATOR_REVIEW", result["status"])
        self.assertEqual("EXECUTABLE", self.answer(packets(), "Q2", "Yes, completed years.")["status"])

    def test_conflicting_replays_and_amendments(self):
        self.build(packets([QUESTION]))
        result = self.answer(packets())
        fail = Mock(side_effect=AssertionError())
        self.assertEqual(result["revision"], self.answer(fail)["revision"])
        self.assertEqual(result["revision"], self.build(fail)["revision"])
        with self.assertRaises(ValueError):
            self.answer(fail, answer="Another answer.")
        with self.assertRaises(ValueError):
            self.build(fail, text=TEXT+" Amended.")
        with self.assertRaises(ValueError):
            self.build(fail, polarity="exclusion")
        self.assertEqual(0, fail.call_count)
        changed = self.build(packets([QUESTION]), scope=(STUDY,"research-v2","I1"), polarity="exclusion")
        self.assertEqual([], changed["answers"])
        self.assertEqual("exclusion", changed["initial_sources"]["polarity"])

    def test_provider_error_preserves_answer_and_retry(self):
        self.build(packets([QUESTION]))
        fail = Mock(side_effect=OSError("secret-value"))
        failed = self.answer(fail)
        self.assertEqual(rules.FAILED, failed["status"])
        self.assertNotIn("secret-value", json.dumps(failed))
        self.assertEqual(1, len(failed["answers"]))
        retried = self.store.retry(*SCOPE, packets())
        self.assertEqual(rules.READY, retried["status"])
        self.assertEqual(1, len(retried["answers"]))
        self.assertEqual(["input_pinned","authoring_completed","answer_recorded","authoring_failed",
                          "authoring_completed"], [r["event"] for r in self.store.history(*SCOPE)])

    def test_explicit_retry_after_failed_verification(self):
        original = self.build(lambda *_: {"bad":"schema"})
        self.assertEqual("VALIDATION_REVIEW", original["status"])
        failed = Mock(side_effect=AssertionError())
        self.assertEqual(original, self.build(failed))
        self.assertEqual("EXECUTABLE", self.store.retry(*SCOPE, packets())["status"])

    def test_mismatched_scope_catalog_or_unreproduced_receipt(self):
        rule = self.build(packets(), text="At least 18 years of age at screening.")["rule"]
        bundle = box(STUDY, "1990-01-01")
        for name, arg in (("study","Other"), ("version","Other"), ("criterion_id","Other"), ("expected_sha256","0"*64)):
            with self.subTest(name=name), self.assertRaises(ValueError):
                rules.screen(rule, bundle, "demo", "screen", CUTOFF, **{name:arg})
        bad = copy.deepcopy(rule)
        bad["expression"]["value"] = 12
        with self.assertRaises(ValueError):
            rules.screen(bad, bundle, "demo", "screen", CUTOFF)
        for th, value in (("catalog", {"facts":{"age":{}}}), ("sources", {"criterion":"Different"})):
            bad = dict(rule)
            bad[th] = value
            bad["sha256"] = rules.digest({k:v for k,v in bad.items() if k!="sha256"})
            with self.assertRaises(ValueError):
                rules.screen(bad, bundle, "demo", "screen", CUTOFF)

    def test_atomic_export_repeated_and_conflicted(self):
        rule = self.build(packets())["rule"]
        out = Path(self.temp.name) / "out" / "rule.json"
        rules.atomic_export(out, rule)
        rules.atomic_export(out, rule)
        with self.assertRaises(ValueError):
            rules.atomic_export(out, {"other":"document"})
        self.assertEqual(rule, json.loads(out.read_text()))

    def test_action_queue_shows_only_current_items_for_each_owner(self):
        untouched = Path(self.temp.name) / "unused"
        self.assertEqual([], rules.RuleStore.actions(untouched, "investigator"))
        self.assertFalse(untouched.exists())
        self.build(packets([QUESTION]))
        def binding_gap(task, packet):
            row = {"source_id": "criterion", "quote": TEXT}
            if task == "author":
                return {"status":"BINDING_REVIEW", "expression":None, "reason":"Mapping missing.",
                        "questions":[], "gaps":["Verify the mapping."], "citations":[row]}
            return {"verdict":"PASS", "reason":"Mapping missing.", "questions":[], "gaps":["Verify the mapping."],
                    "obligations":[{**row, "coverage":"GAP", "detail":"Mapping is missing."}]}
        self.build(binding_gap, scope=(STUDY, "research-v1", "I2"))
        self.build(lambda *_: {}, scope=(STUDY, "research-v1", "I3"))
        self.build(Mock(side_effect=RuntimeError("secret-value")), scope=(STUDY, "research-v1", "I4"))
        question, = self.store.actions(self.temp.name, "investigator")
        self.assertEqual({"study":STUDY, "version":"research-v1", "id":"I1", "kind":"investigator_question",
                          "question_id":"Q1", "text":QUESTION}, question)
        items = self.store.actions(self.temp.name, "engineering")
        self.assertEqual(["binding_gap","validation_review","provider_error"], [i["kind"] for i in items])
        for item in items:
            self.assertEqual({"study","version","id","kind","text"}, set(item))
        self.assertNotIn("secret-value", json.dumps(items))
        self.answer(packets())
        self.assertEqual([], self.store.actions(self.temp.name, "investigator"))

    def test_concurrent_identical_submissions_call_provider_once(self):
        wait = threading.Barrier(2)
        provider = Mock(side_effect=packets())
        def submit():
            wait.wait(timeout=4)
            return self.build(provider)["rule"]["sha256"]
        with ThreadPoolExecutor(2) as pool:
            a,b = [pool.submit(submit) for _ in range(2)]
            self.assertEqual(a.result(), b.result())
        self.assertEqual(2, provider.call_count)


if __name__ == "__main__":
    unittest.main()
