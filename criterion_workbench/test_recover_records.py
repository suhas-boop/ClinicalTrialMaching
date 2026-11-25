from copy import deepcopy
import json
from pathlib import Path
import unittest

from recover_records import recover
from bindings import make_packet

ROOT = Path(__file__).resolve().parents[1]
V = "a" * 64
AT = "2025-03-02T12:00:00Z"
EARLY = "2025-03-01T12:00:00Z"


def example():
    rules = json.loads((ROOT / "nih_benchmark/round2/rules.json").read_text())
    rules = {k: rules[k] for k in ("115", "116")}
    base = make_packet(rules, {}, "NCT02512159", V, stamp=AT)
    chart = make_packet(rules, {"116": {"cutaneous_ulcer_due_to_burns": True}}, "NCT02512159", V, stamp=EARLY)
    archive = chart["bundle"]
    archive["entry"] = archive["entry"][3:]
    return rules, base, archive


class Recovery(unittest.TestCase):
    def setUp(self):
        self.rules, self.base, self.archive = example()
        self.doc, self.obs = [e["resource"] for e in self.archive["entry"]]

    def run_case(self):
        return recover(self.rules, self.base, self.archive, "NCT02512159", V)

    def state(self):
        return self.run_case()["transitions"]["116"]["after"]

    def test_same_wound_distinct_decisions(self):
        result = self.run_case()
        self.assertEqual(["116"], result["new_evidence_backed_decisions"])
        self.assertEqual("NOT_MET", result["transitions"]["116"]["after"])
        self.assertEqual("MISSING_DATA", result["transitions"]["115"]["after"])
        self.assertEqual(2, len(result["transitions"]["116"]["evidence"]))

    def test_documented_negative(self):
        self.obs["valueBoolean"] = False
        self.assertEqual("MET", self.state())

    def test_empty_and_unlinked(self):
        self.archive["entry"] = []
        self.assertEqual("MISSING_DATA", self.state())
        self.archive["entry"] = [{"resource": self.obs}]
        self.assertEqual("MISSING_DATA", self.state())

    def test_other_scope(self):
        for path, val in [("subject","Patient/other"), ("encounter","Encounter/other")]:
            with self.subTest(path):
                original = deepcopy(self.obs)
                self.obs[path]["reference"] = val
                self.assertEqual("MISSING_DATA", self.state())
                self.obs.update(original)
        self.obs["focus"][0]["reference"] = "Condition/other"
        self.assertEqual("MISSING_DATA", self.state())

    def test_wrong_protocol(self):
        self.obs["code"]["coding"][0]["version"] = "other"
        self.assertEqual("MISSING_DATA", self.state())

    def test_untrusted_author(self):
        self.doc["author"] = [{"reference": "Organization/unknown"}]
        self.assertEqual("MISSING_DATA", self.state())

    def test_duplicate_delivery(self):
        first = self.run_case()
        self.archive["entry"] += deepcopy(self.archive["entry"])
        self.assertEqual(first, self.run_case())
        self.base["bundle"]["entry"].extend(self.archive["entry"])
        repeated = self.run_case()
        self.assertFalse(repeated["new_resource_versions"])
        self.assertFalse(repeated["new_evidence_backed_decisions"])

    def revise(self, resource, **changes):
        amended = deepcopy(resource)
        amended["meta"].update(versionId="2", lastUpdated=AT)
        amended.update(changes)
        self.archive["entry"].append({"resource": amended})
        return amended

    def test_changed_finding(self):
        self.revise(self.obs, status="corrected", valueBoolean=False)
        self.assertEqual("MET", self.state())

    def test_future_amendment(self):
        new = self.revise(self.obs, status="corrected", valueBoolean=False)
        new["meta"]["lastUpdated"] = "2025-03-03T00:00:00Z"
        self.assertEqual("NOT_MET", self.state())

    def test_withdrawal_of_decided_evidence(self):
        self.base["bundle"]["entry"] += deepcopy(self.archive["entry"])
        self.archive["entry"] = []
        self.revise(self.doc, status="entered-in-error")
        self.assertEqual({"before":"NOT_MET", "after":"MISSING_DATA","evidence":[]},
                         self.run_case()["transitions"]["116"])

    def test_contradictory_independent_findings(self):
        other = deepcopy(self.obs)
        other.update(id="second", valueBoolean=False)
        self.archive["entry"].append({"resource": other})
        self.assertEqual("MISSING_DATA", self.state())

    def test_version_collision(self):
        other = deepcopy(self.obs)
        other["valueBoolean"] = False
        self.archive["entry"].append({"resource": other})
        with self.assertRaisesRegex(ValueError,"Conflicting copies"):
            self.run_case()

    def test_reassigned_document(self):
        self.revise(self.doc, subject={"reference":"Patient/other"})
        with self.assertRaisesRegex(ValueError,"identity"):
            self.run_case()

    def test_disabled_binding(self):
        self.base["context"]["enabled_contracts"] = []
        self.assertEqual("BINDING_HOLD", self.state())

    def test_imaging(self):
        rule = json.loads((ROOT / "nih_benchmark/round2/rules.json").read_text())["460"]
        rules = {"460": rule}
        s = "NCT00282269"
        base = make_packet(rules, {"460": {"traumatic_brain_injury":True, "gcs":6}}, s, V, stamp=AT)
        chart = make_packet(rules, {"460":{"ct_intracranial_hemorrhage":True}}, s, V, stamp=EARLY)
        result = recover(rules, base, chart["bundle"], s, V)["transitions"]["460"]
        self.assertEqual(("MISSING_DATA","MET"), (result["before"], result["after"]))
        self.assertEqual(6, len(result["evidence"]))

    def test_released_study_entrypoint(self):
        from review_study import run
        folder = ROOT / "eight_rules/release/examples"
        base = json.loads((folder/"1479-0032-empty.json").read_text())
        populated = json.loads((folder/"1479-0032-met.json").read_text())
        expected = run(populated)
        actual = run(base, populated["bundle"])
        self.assertTrue(actual["archive_recovery"]["changes"])
        self.assertEqual(expected["criteria"], actual["criteria"])
        self.assertEqual(expected["requests"], actual["requests"])
