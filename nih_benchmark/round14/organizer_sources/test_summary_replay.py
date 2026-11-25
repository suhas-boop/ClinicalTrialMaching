"""Validate case and group scope, source integrity, conflict handling and blind replay."""
import argparse
import csv
from pathlib import Path
import sys
import unittest

from source_join import digest
from summary_replay import STAMP, read, run

cli = argparse.ArgumentParser()
cli.add_argument("benchmark", type=Path)
args, test_args = cli.parse_known_args()
ROOT = args.benchmark


class PublishedSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run(ROOT)

    def test_inventory_subject_scope_and_no_patient_from_group(self):
        r = self.result
        self.assertEqual((r["notes_joined"], r["subjects_with_assignments"], r["rule_pairs"], r["group_assignments"]), (53, 44, 134, 8))
        group = r["subjects"]["sigir-201426"]
        self.assertEqual(group["source_resource_type"], "Group")
        self.assertFalse(group["separately_ingested_clinical_facts"])
        for case in r["cases"]:
            if case["subject"].startswith("Group/"):
                self.assertIn(case["with_summary"], ("SOURCE_SCOPE_HOLD", "AUTHORING_HOLD"))
                self.assertFalse(case["summary_evidence"])

    def test_summary_inputs_exact_and_bound_to_correct_subject(self):
        for subject, source in self.result["subjects"].items():
            self.assertEqual(source["summary_sha256"], digest(source["summary"].encode()))
            for fact in source["separately_ingested_clinical_facts"]:
                self.assertIn("/", fact["resource"])
            self.assertEqual(subject, source["subject_id"])
        for case in self.result["cases"]:
            for loc in case["summary_evidence"].values():
                patient = case["subject"].split("/", 1)[1]
                source = self.result["subjects"][patient]
                self.assertEqual(loc["document"], "DocumentReference/" + patient + "-trec-summary")
                self.assertEqual(loc["sha256"], source["summary_sha256"])

    def test_all_outcomes_and_corroboration(self):
        with (ROOT / "round14/results/134_predictions.csv").open() as stream:
            expected = {r["annotation"]:r["current"] for r in csv.DictReader(stream)}
        observed = {r["case"]:r["baseline"] for r in self.result["cases"]}
        self.assertEqual(observed, expected)
        self.assertEqual(self.result["changed_outcomes"], [])
        self.assertEqual(self.result["changed_operands"], [])
        self.assertTrue(self.result["summary_cited_by_rule"])

    def test_original_publications_with_conflicting_ages_stay_distinct(self):
        from record_arrivals import evaluate, receive
        from screen import verify
        pack = verify(read(ROOT / "round11/compiled.json"))
        patient = "sigir-20157"
        note = read(ROOT / "round9/notes.json")[patient]
        summary = self.result["subjects"][patient]["summary"]
        self.assertIn("20 y", note)
        self.assertIn("22 year", summary)
        encounter = "conflict-control"
        n = receive(patient, encounter, patient+"-note", note, STAMP)
        s = receive(patient, encounter, patient+"-summary", summary, STAMP)
        # An existing age rule is used only in this unscored control.
        key = "44"
        study = pack["rules"][key]["source"]["trial_id"]
        decision = lambda data:evaluate(data,patient,encounter,pack,study,[key])["criteria"][key]["state"]
        self.assertEqual(decision(n+s), "MISSING_DATA")
        self.assertEqual(decision(s), "MET")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], *test_args])
