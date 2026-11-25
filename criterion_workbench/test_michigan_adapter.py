"""Check the unified compiler against the three Michigan rule and evidence paths."""
import json
import sys
import unittest
from copy import deepcopy
from zipfile import ZipFile

from compiler import compile_draft, evaluate, screen
from michigan_adapter import APP, STUDY, author_context, leaves, reference_rule


def bundle_for(case):
    sys.path.insert(0, str(APP))
    try:
        from charts import bundle_entries
    finally:
        sys.path.pop(0)
    with ZipFile(APP) as archive:
        catalog = json.loads(archive.read("data/catalog.json"))
        cases = json.loads(archive.read("data/charts.json"))
    rows = bundle_entries(next(x for x in cases if x["id"] == case), "demo-", catalog)
    entries = [{"resource":{**row["resource"], "meta":{"versionId":"1"}}} for row in rows]
    return {"resourceType":"Bundle", "type":"collection", "entry":entries}


def inputs(criterion):
    packet = {"study":STUDY, "criterion_id":criterion, "polarity":"inclusion",
              "protocol_sha256":screen.INVENTORY["studies"][STUDY]["protocol_sha256"],
              "catalog_version":screen.CATALOG_DATA["version"]}
    ref = reference_rule(criterion, packet["protocol_sha256"])
    tree = ref["expression"]
    draft = {**packet, "disposition":"EXECUTABLE", "executable":deepcopy(tree), "draft":deepcopy(tree),
             "obligations":[{"id":"synthetic-test", "statement":ref["source"]["text"],
                             "source_locator":ref["source"]["locator"]["word_paragraph_id"]}],
             "bindings":[{"fact":key, "catalog_key":key, "status":"BOUND"} for key in sorted(leaves(tree))],
             "clinical_questions":[]}
    return packet, draft


class MichiganIntegration(unittest.TestCase):
    def test_all_criteria_and_native_routing(self):
        for case, cid, expected in (
            ("all-met","MI-LMS-01","MET"), ("all-met","MI-LMS-02","MET"), ("all-met","MI-LMS-03","MET"),
            ("localized","MI-LMS-01","NOT_MET"), ("liposomal","MI-LMS-02","AUTHORING_HOLD"),
            ("unknown-product","MI-LMS-02","BINDING_HOLD"), ("other-course","MI-LMS-03","MISSING_DATA"),
        ):
            with self.subTest(case=case, cid=cid):
                packet, draft = inputs(cid)
                compiled = compile_draft(packet, draft)
                self.assertEqual(compiled["state"], "READY", compiled)
                patient, episode = "demo-" + case + "-p", "demo-" + case + "-current"
                result = evaluate(compiled, bundle_for(case), patient, None, "2026-04-15", episode=episode)
                self.assertEqual(result["state"], expected, result)
                self.assertEqual(result["source_locator"]["word_paragraph_id"], compiled["source_locator"]["word_paragraph_id"])
                self.assertTrue(result["requests"])
                self.assertIn("Condition/" + episode + "/_history/1", result["evidence"])

    def test_episode_and_patient_scope(self):
        packet, draft = inputs("MI-LMS-01")
        compiled = compile_draft(packet, draft)
        bundle = bundle_for("all-met")
        for patient, episode in [("demo-all-met-p",None),("unrelated-patient","demo-all-met-current"),
                                 ("demo-all-met-p","demo-all-met-prior")]:
            with self.subTest(patient=patient, episode=episode):
                result = evaluate(compiled, bundle, patient, None, "2026-04-15", episode=episode)
                self.assertEqual(result["state"], "MISSING_DATA", result)

    def test_boolean_contract_and_catalog_isolation(self):
        packet, draft = inputs("MI-LMS-01")
        # Same truth table, original reference order will still be used by the evaluator.
        draft["executable"]["all"][1]["any"].reverse()
        self.assertEqual(compile_draft(packet, draft)["state"], "READY")
        for bad in ({"any":["lms","metastatic","unresectable"]}, {"all":["lms"]}, {"all":["age"]},
                    {"all":["lms",{"any":["metastatic","unresectable"]}],"overrides":True}):
            with self.subTest(bad=bad):
                edited = {**draft,"draft":bad,"executable":bad}
                self.assertEqual(compile_draft(packet, edited)["state"], "VALIDATION_HOLD")
        draft["bindings"].pop()
        self.assertEqual(compile_draft(packet, draft)["state"], "VALIDATION_HOLD")
        self.assertEqual(author_context("other-study"), {})
        ctx = author_context(STUDY)
        self.assertIn("lms", ctx["episode_evidence_catalog"]["facts"])
        self.assertNotIn('"expression"', json.dumps(ctx))
        self.assertNotIn("protocol_sha256", ctx["episode_evidence_catalog"])

    def test_missing_future_source_is_withheld(self):
        packet, draft = inputs("MI-LMS-01")
        compiled = compile_draft(packet, draft)
        bundle = bundle_for("all-met")
        for entry in bundle["entry"]:
            if entry["resource"]["resourceType"] == "Observation":
                entry["resource"]["meta"]["lastUpdated"] = "2026-04-16T01:00:00Z"
        result = evaluate(compiled, bundle, "demo-all-met-p", None,
                          "2026-04-15T23:30:00Z", episode="demo-all-met-current")
        self.assertEqual(result["state"], "MISSING_DATA", result)
