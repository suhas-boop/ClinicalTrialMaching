import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
from study_scope import (BENCH, DEFAULT_CATALOG, ORIGINALS, age_window, assess, extract_index_age,
                         fingerprint, read_json, original_registry, run, verified_age, verify)
import sys
sys.path.insert(0, str(BENCH / "round12"))
from intake import plain_chart


class StudyAgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = verify(read_json(DEFAULT_CATALOG))
        cls.study = "NCT00839124"
        cls.subject = "Patient/test-case"

    def resources(self, note):
        bundle, _ = plain_chart("test-case", note, "2026-01-01T00:00:00Z")
        return [e["resource"] for e in bundle["entry"]]

    def test_endpoint_bounds(self):
        bounds = {"minimumAge":"18 Years", "maximumAge":"50 Years"}
        self.assertEqual(age_window(17, bounds)[1], "BELOW_MINIMUM")
        self.assertEqual(age_window(51, bounds)[1], "ABOVE_MAXIMUM")
        for age in (18, 35, 50):
            self.assertEqual(age_window(age, bounds)[0], "NO_DEFINITE_AGE_EXCLUSION")

    def test_other_units_and_missing_limit(self):
        self.assertEqual(age_window(0, {"minimumAge":"7 Months"})[0], "NO_DEFINITE_AGE_EXCLUSION")
        self.assertEqual(age_window(55, {"minimumAge":"1 Month", "maximumAge":"18 Years"})[1], "ABOVE_MAXIMUM")
        self.assertEqual(age_window(0, {})[0], "UNRATED")
        self.assertEqual(age_window(5, {"minimumAge":"20 Years","maximumAge":"2 Years"})[0], "UNRATED")

    def test_age_reference_with_provenance(self):
        note = "A 4-year-old boy presents with wheeze."
        items = self.resources(note)
        age, issue = verified_age(items, self.subject, self.study, self.pack)
        self.assertIsNone(issue)
        self.assertEqual(age["excerpt"], note)
        self.assertEqual(age["source_sha256"], fingerprint(note.encode()))
        self.assertTrue(all(x.startswith("Observation/") for x in age["resources"]))
        self.assertEqual(verified_age(items, self.subject, self.study, self.pack, "wrong")[1], "PATIENT_SOURCE_HASH_MISMATCH")
        without_provenance = [r for r in items if r["resourceType"] != "Provenance"]
        self.assertIsNone(verified_age(without_provenance, self.subject, self.study, self.pack)[0])

    def test_unsupported_subject_age_and_conflict(self):
        for note in ("Presents with wheezing.", "Family history:\nA 4-year-old boy presents with wheeze.",
                     "A 4-year-old boy's brother presents with wheezing.",
                     "A 46-year-old woman presents with her 4-year-old son for his fever.",
                     "A 46-year-old woman presents to discuss her daughter’s symptoms.",
                     "A 4-year-old boy presents with wheeze.\nA 44-year-old man presents with cough."):
            self.assertIsNone(verified_age(self.resources(note), self.subject, self.study, self.pack)[0], msg=note)
        self.assertIsNone(verified_age([], "Group/example", self.study, self.pack)[0])

    def test_changed_result_or_unattached_source(self):
        items = self.resources("A 4-year-old boy presents with wheeze.")
        obs = next(r for r in items if r["resourceType"]=="Observation" and r.get("valueQuantity"))
        obs["valueQuantity"]["value"] = 80
        self.assertIsNone(verified_age(items, self.subject, self.study, self.pack)[0])
        obs["valueQuantity"]["value"] = 4
        obs["subject"] = {"reference":"Patient/wrong"}
        self.assertIsNone(verified_age(items, self.subject, self.study, self.pack)[0])

    def test_source_identity(self):
        entries = {"850":deepcopy(self.pack["rules"]["850"])}
        with TemporaryDirectory() as tmp, patch("study_scope.ORIGINALS",Path(tmp)):
            tmp = Path(tmp)
            (tmp/"xml").mkdir()
            manifest = read_json(ORIGINALS/"manifest.json")
            wrong = (ORIGINALS/"xml/NCT00163709.xml").read_bytes()
            (tmp/"xml"/(self.study+".xml")).write_bytes(wrong)
            (tmp/"manifest.json").write_bytes((ORIGINALS/"manifest.json").read_bytes())
            self.assertEqual(original_registry(self.study, entries)[1], "REGISTRY_HASH_MISMATCH")
            manifest["studies"][self.study]["sha256"] = fingerprint(wrong)
            raw=json.dumps(manifest).encode()
            (tmp/"manifest.json").write_bytes(raw)
            self.assertEqual(original_registry(self.study, entries)[1], "ARCHIVE_MANIFEST_HASH_MISMATCH")
            with patch("study_scope.MANIFEST_SHA256", fingerprint(raw)):
                self.assertEqual(original_registry(self.study, entries)[1], "REGISTRY_IDENTITY_MISMATCH")
        self.assertIsNone(original_registry("../other", {})[0])

    def test_age_from_source_months_and_near_boundaries(self):
        items = [e["resource"] for e in read_json(BENCH/"round12/export/bundles/sigir-201418.json")["entry"]]
        result = assess(items, "Patient/sigir-201418", "NCT00557219", self.pack)
        self.assertEqual(result["reason"], "BELOW_MINIMUM")
        self.assertEqual((result["patient_age"]["value"], result["patient_age"]["unit"]),(6, "mo"))
        self.assertEqual(age_window(216, {"minimumAge":"18 Years"}, "mo")[0], "NO_DEFINITE_AGE_EXCLUSION")
        self.assertEqual(age_window(215, {"minimumAge":"18 Years"}, "mo")[1], "BELOW_MINIMUM")
        self.assertEqual(age_window(1, {"minimumAge":"365 Days"}, "a")[0], "NO_DEFINITE_AGE_EXCLUSION")
        self.assertEqual(age_window(365, {"maximumAge":"1 Year"}, "d")[0], "NO_DEFINITE_AGE_EXCLUSION")
        self.assertEqual(age_window(10, {"minimumAge":"2 Months", "maximumAge":"5 Days"}, "d")[0], "UNRATED")

    def test_fresh_month_and_day_fhir_intake(self):
        for note, val, unit in (("A 6-month-old male infant presents with low urine output.",6,"mo"),
                                ("A 12-day-old infant presents with fever.",12,"d")):
            receipt = assess(self.resources(note),self.subject,"NCT00557219",self.pack)
            self.assertEqual(receipt["reason"],"BELOW_MINIMUM")
            self.assertEqual((receipt["patient_age"]["value"],receipt["patient_age"]["unit"]),(val,unit))
            self.assertEqual(receipt["patient_age"]["source_sha256"],fingerprint(note.encode()))

    def test_prior_enrollment_requires_prior_age(self):
        items = [e["resource"] for e in read_json(BENCH/"round12/export/bundles/sigir-20148.json")["entry"]]
        result = assess(items,"Patient/sigir-20148","NCT01628315",self.pack)
        self.assertEqual(result["state"],"UNRATED")
        self.assertIn(result["reason"],["HISTORICAL_ENROLLMENT_AGE_REQUIRED","BENCHMARK_REGISTRATION_VERSION_UNVERIFIED"])

    def test_age_scope_is_independent_of_annotated_criterion(self):
        items = self.resources("A 4-year-old boy presents to the emergency department with wheezing.")
        receipt = assess(items, self.subject, self.study, self.pack)
        self.assertEqual(receipt["reason"], "BELOW_MINIMUM")
        self.assertEqual(receipt["criterion_ids_for_study"], ["850"])
        self.assertEqual(receipt["registration"]["bounds"]["minimumAge"], "18 Years")
        self.assertEqual(receipt["scope"], "study_age_at_presentation")
        self.assertNotIn("criteria", receipt)
        self.assertNotIn("study_eligible", receipt)

    def test_every_frozen_age_exclusion_replays_from_raw_notes(self):
        notes = read_json(BENCH / "round9/notes.json")
        hashes = read_json(BENCH / "round9/note_hashes.json")
        confirmed = set()
        for row in run()["receipts"]:
            if row["state"] != "EXCLUDED_BY_AGE_AT_PRESENTATION":
                continue
            patient = row["subject"].split("/")[1]
            bundle, _ = plain_chart(patient,notes[patient],"2026-01-01T00:00:00Z")
            result = assess([entry["resource"] for entry in bundle["entry"]],row["subject"],row["study"],
                            self.pack,expected_hash=hashes[patient])
            self.assertEqual((result["state"],result["reason"]),(row["state"],row["reason"]))
            confirmed.add(row["study"])
        self.assertEqual(len(confirmed),5)

    def test_replay_retains_all_pairs(self):
        output = run()
        self.assertEqual((output["assignments"], output["patient_study_pairs"]), (134, 68))
        self.assertEqual(output["patient_study_pairs"],len({(r["subject"], r["study"]) for r in output["receipts"]}))
        ids = [i for r in output["receipts"] for i in r["assigned_criterion_ids"]]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(len(ids),134)
        for receipt in output["receipts"]:
            self.assertNotIn(receipt["state"], {"MET", "NOT_MET", "ELIGIBLE"})


if __name__ == "__main__":
    unittest.main()
