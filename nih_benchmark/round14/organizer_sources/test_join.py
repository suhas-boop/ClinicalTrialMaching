"""Independent controls for mutable/incorrect subject identity and eligibility specificity."""
import argparse
from pathlib import Path
import sys
import tempfile
import unittest

from source_join import description_match, frozen_description, join, pinned
from replay import load, project, resources, run, STAMP

parser = argparse.ArgumentParser()
parser.add_argument("benchmark", type=Path)
args, unittest_args = parser.parse_known_args()
ROOT = args.benchmark


class JoinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = join(ROOT)
        cls.result = run(ROOT)

    def test_all_pinned_notes_match_with_units_preserved(self):
        self.assertEqual(len(self.records), 53)
        differing = [p for p, r in self.records.items() if "temperature" in r["same_case_check"]]
        self.assertEqual(differing, ["sigir-201520"])
        with self.assertRaises(ValueError):
            description_match("A temperature of 38 F.", "A temperature of 38°C.")
        with self.assertRaises(ValueError):
            description_match("Hgb >9", "Hgb <9")

    def test_same_topic_id_cannot_override_different_patient_text(self):
        with self.assertRaises(ValueError):
            description_match("Two 40-year-old patients", "A 56-year-old woman")
        with self.assertRaises(ValueError):
            frozen_description("0. A patient.\n2. A different sentence.")

    def test_integrity_check_rejects_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "topics2015B.xml"
            file.write_text("<topics/>")
            with self.assertRaises(ValueError):
                pinned(file)

    def test_all_supplement_subjects_and_source_projections_match(self):
        extra = [p for p, r in self.records.items() if r["supplement"]]
        self.assertEqual(len(extra), 15)
        self.assertEqual(self.result["subjects_with_assigned_rules_and_addenda"], 13)
        notes = load(ROOT / "round9/notes.json")
        for pid in extra:
            x = self.records[pid]["supplement"]
            self.assertEqual(x["fhir"]["subject"]["reference"], "Patient/" + pid)
            composite, span, _ = project(notes[pid], x)
            self.assertEqual(composite[slice(*span)], x["wording"])
            self.assertTrue(composite.startswith(notes[pid] + "\n"))

    def test_all_assigned_criteria_evaluated(self):
        cases = self.result["cases"]
        self.assertEqual(len(cases), 41)
        self.assertEqual(len({r["case"] for r in cases}), 41)
        self.assertTrue(all(r["expanded_source_hash_verified"] for r in cases))
        self.assertEqual(self.result["eligibility_state_changes"], [])
        self.assertEqual(self.result["clinical_operand_changes"], [])
        self.assertIn("sigir-201511", self.result["subjects_with_extracted_supplemental_facts"])

    def test_generic_vs_specified_diagnosis_uses_normal_pipeline(self):
        from intake import plain_chart
        from screen import verify, screen
        pack = verify(load(ROOT / "round11/compiled.json"))
        scenarios = {
            "The patient has lupus.": "MISSING_DATA",
            "The patient has systemic lupus erythematosus.": "MET",
            "The patient denies systemic lupus erythematosus.": "NOT_MET",
        }
        for note, expected in scenarios.items():
            bundle, spans = plain_chart("control", note, STAMP)
            result = screen(resources(bundle), "Patient/control", pack, "NCT01520155", "414")["criteria"]["414"]
            self.assertEqual(result["state"], expected)
            self.assertEqual(bool(result["evidence"]), expected != "MISSING_DATA")
        self.assertEqual(self.records["sigir-201421"]["supplement"]["wording"], "lupus")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], *unittest_args])
