"""Regression cases for the research compiler and the saved review path."""

from copy import deepcopy
from pathlib import Path
import json
import unittest

from compiler import compile_draft, evaluate, screen

CRITERION = "NEOK001-1-I02"
CUTOFF = "2026-05-01T19:00:00Z"


def packet_for(criterion):
    row = next(r for r in screen.INVENTORY["criteria"] if r["id"] == criterion)
    source = screen.INVENTORY["studies"][row["study"]]
    return {"criterion_id": criterion, "study": row["study"], "polarity": row["polarity"],
            "protocol_sha256": source["protocol_sha256"], "catalog_version": screen.CATALOG_DATA["version"]}


def age_candidate():
    pkt = packet_for(CRITERION)
    rule = {"fact": "age", "operator": "ge", "threshold": 18}
    return {**pkt, "disposition": "EXECUTABLE", "draft": deepcopy(rule), "executable": rule,
            "obligations": [{"id": "adult", "statement": "Participant must be age 18 or older.",
                             "source_locator": "Amendment 2, §5.1(2), page 49"}],
            "clinical_questions": [],
            "bindings": [{"status": "BOUND", "fact": "Age in completed years on screening day.", "catalog_key": "age"}]}


def bundle(birthdate=None):
    patient = {"resourceType": "Patient", "id": "synthetic", "meta": {"versionId": "2", "lastUpdated": CUTOFF}}
    if birthdate:
        patient["birthDate"] = birthdate
    enc = {"resourceType": "Encounter", "id": "s1", "meta": {"versionId": "1", "lastUpdated": CUTOFF},
           "subject": {"reference": "Patient/synthetic"}, "status": "in-progress",
           "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"},
           "period": {"start": "2026-05-01T08:00:00Z"},
           "identifier": [{"system": "urn:pocketmd:demo:screening-study", "value": "NEOK001-1"}]}
    return {"resourceType": "Bundle", "type": "collection", "entry": [{"resource": patient}, {"resource": enc}]}


class TestResearchCompiler(unittest.TestCase):
    def test_ready_boundary_missing_and_source_trace(self):
        compiled = compile_draft(packet_for(CRITERION), age_candidate())
        self.assertEqual(compiled["state"], "READY", compiled)
        self.assertEqual(compiled["queries"][0]["selector"]["value"], "Patient.birthDate")
        for date, expected in [("2008-05-01", "MET"), ("2008-05-02", "NOT_MET"), (None, "MISSING_DATA")]:
            with self.subTest(date=date):
                result = evaluate(compiled, bundle(date), "synthetic", "s1", CUTOFF)
                self.assertEqual(result["state"], expected, result)
                self.assertEqual(result["evidence"], ["Encounter/s1/_history/1", "Patient/synthetic/_history/2"]
                                 if expected != "MISSING_DATA" else ["Patient/synthetic/_history/2", "Encounter/s1/_history/1"])
                self.assertEqual(result["as_of"], CUTOFF)
                self.assertEqual(result["protocol_sha256"], compiled["protocol_sha256"])

    def test_model_errors_do_not_reach_an_outcome(self):
        pk = packet_for(CRITERION)
        for field, value in [
                ("protocol_sha256", "different-amendment"), ("catalog_version", "other"),
                ("polarity", "exclusion"), ("study", "other"), ("obligations", []),
                ("obligations", [{"id":"fake", "statement":"Age minimum", "source_locator":"page 1"}]),
                ("draft", {"fact": "age", "operator": "lt", "threshold": 18}),
                ("clinical_questions", [{"question": "Which threshold applies?"}]),
                ("bindings", [{"status": "BOUND", "fact": "age", "catalog_key": "fabricated"}]),
                ("bindings", []), ("queries", [{"path": "Patient.name"}])]:
            with self.subTest(field=field):
                d = age_candidate()
                d[field] = value
                rejection = compile_draft(pk, d)
                self.assertEqual(rejection["state"], "VALIDATION_HOLD", rejection)
                self.assertIsNone(rejection["executable"])
                self.assertEqual(evaluate(rejection, bundle(), "synthetic", "s1", CUTOFF)["state"], "VALIDATION_HOLD")
        for edits in ({"operator": "gt"}, {"threshold": 19}, {"threshold": True}, {"require_male": True}):
            with self.subTest(edits=edits):
                d = age_candidate()
                d["draft"].update(edits)
                d["executable"].update(edits)
                self.assertEqual(compile_draft(pk, d)["state"], "VALIDATION_HOLD")

    def test_invalid_snapshot_or_changed_compiled_plan(self):
        compiled = compile_draft(packet_for(CRITERION), age_candidate())
        wrong_bundle = bundle("2000-01-01")
        wrong_bundle["entry"][1]["resource"]["subject"]["reference"] = "Patient/different"
        self.assertEqual(evaluate(compiled, wrong_bundle, "synthetic", "s1", CUTOFF)["state"], "MISSING_DATA")
        tampered = deepcopy(compiled)
        tampered["executable"]["threshold"] = 21
        self.assertEqual(evaluate(tampered, bundle("2000-01-01"), "synthetic", "s1", CUTOFF)["state"], "VALIDATION_HOLD")

    def test_answer_reconciliation_requires_exact_scoped_ids(self):
        packet = packet_for(CRITERION)
        packet["answers"] = [{"question_id":"review-123", "study": packet["study"], "criterion_id": CRITERION,
                              "protocol_sha256": packet["protocol_sha256"], "answer":"Use the screening day."}]
        for claim in ([], ["wrong-id"], ["review-123", "review-123"]):
            draft = {**age_candidate(), "applied_question_ids": claim}
            self.assertEqual(compile_draft(packet, draft)["state"], "VALIDATION_HOLD")
        draft = {**age_candidate(), "applied_question_ids": ["review-123"]}
        checked = compile_draft(packet, draft)
        self.assertEqual(checked["state"], "READY", checked)
        self.assertEqual(checked["applied_question_ids"], ["review-123"])
        packet["answers"][0]["protocol_sha256"] = "outdated"
        self.assertEqual(compile_draft(packet, draft)["state"], "VALIDATION_HOLD")

    def test_external_input_cannot_shadow_registered_study(self):
        packet = {**packet_for(CRITERION), "source_mode": "uploaded_pdf"}
        compiled = compile_draft(packet, age_candidate())
        self.assertEqual(compiled["state"], "VALIDATION_HOLD")

    def test_saved_hold_keeps_review_and_evidence_gaps(self):
        draft = json.loads((Path(__file__).parent / "examples/i18-author.json").read_text())
        compiled = compile_draft(packet_for(draft["criterion_id"]), draft)
        self.assertEqual(compiled["state"], "PROTOCOL_AND_BINDING_REVIEW", compiled)
        self.assertEqual(len(compiled["questions"]), 3)
        self.assertEqual(len(compiled["binding_gaps"]), 4)
        result = evaluate(compiled, None, None, None, CUTOFF)
        self.assertEqual(result["state"], compiled["state"])
        self.assertEqual(result["evidence"], [])

    def test_wrong_registered_study_and_unregistered_rule(self):
        wrong = packet_for(CRITERION)
        wrong["study"] = "106S01"
        self.assertEqual(compile_draft(wrong, age_candidate())["state"], "VALIDATION_HOLD")
        row = packet_for("106S01-I18")
        d = {**age_candidate(), **row}
        self.assertEqual(compile_draft(row, d)["state"], "VALIDATION_HOLD")
