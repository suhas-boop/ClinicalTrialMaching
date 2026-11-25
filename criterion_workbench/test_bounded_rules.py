"""Research qualification cases for the new composable predicate runtime."""

import copy
import unittest

import bounded_rules as rules
from verify import N as STUDY, CUTOFF, box, add


AGE = {"fact": "age", "op": "ge", "value": 18}
ECOG = {"fact": "ecog", "op": "in", "values": [0, 1]}


class BoundedRulesTests(unittest.TestCase):
    def setUp(self):
        self.catalog = rules.approved_catalog()
        self.bundle = box(STUDY, "2008-05-01")

    def run_rule(self, expr, **args):
        inputs = dict(bundle=self.bundle, patient="demo", encounter="screen", study=STUDY, as_of=CUTOFF)
        return rules.evaluate(expr, self.catalog, **{**inputs, **args})

    def test_approved_binding_sourced_and_pinned(self):
        self.assertEqual("four-study-r4", self.catalog["version"])
        self.assertEqual("Patient.birthDate", self.catalog["facts"]["age"]["value"])
        self.assertEqual("89247-1", self.catalog["facts"]["ecog"]["code"])
        self.assertEqual(self.catalog, rules.approved_catalog(keys=["ecog", "age"]))
        altered = copy.deepcopy(self.catalog)
        altered["facts"]["ecog"]["value"] = "Observation.valueString"
        altered["sha256"] = rules.digest({k: v for k, v in altered.items() if k != "sha256"})
        with self.assertRaises(ValueError):
            rules.validate(ECOG, altered)
        source = copy.deepcopy(rules.screen.CATALOG_DATA)
        source["version"] = "four-study-r5"
        with self.assertRaises(ValueError):
            rules.approved_catalog(source)
        with self.assertRaises(ValueError):
            rules.validate(ECOG, rules.approved_catalog(keys=["age"]))
        with self.assertRaises(ValueError):
            rules.approved_catalog(keys=["temperature"])
        with self.assertRaises(ValueError):
            rules.validate(AGE, rules.approved_catalog(keys=[]))

    def test_closed_predicate_language(self):
        invalid = [
            {}, {"any": []}, {"all": "age"}, {"all": [AGE], "any": [ECOG]},
            {"all": [AGE, {"age": 18}]}, {**ECOG, "approved": True},
            {**AGE, "op": "calculate"}, {**ECOG, "values": []},
            {**ECOG, "values": [1, 1]}, {**ECOG, "values": [1, True]},
            {**ECOG, "values": [6]}, {**AGE, "value": 18.0}, {**AGE, "value": -1},
            {"fact": "age", "op": "ge", "values": [18]}, {**AGE, "fact": "lansky"},
        ]
        for expr in invalid:
            with self.subTest(expr=expr), self.assertRaises(ValueError):
                rules.validate(expr, self.catalog)
        self.assertEqual(["age", "ecog"], rules.validate({"all": [AGE, ECOG, AGE]}, self.catalog))

    def test_comparisons_are_parametric(self):
        for op, value, expected in (
            ("eq", 18, "MET"), ("le", 18, "MET"), ("lt", 18, "NOT_MET"),
            ("gt", 17, "MET"), ("ge", 19, "NOT_MET")):
            with self.subTest(op=op):
                self.assertEqual(expected, self.run_rule({"fact": "age", "op": op, "value": value})["state"])
        add(self.bundle, "ecog", 2)
        self.assertEqual("NOT_MET", self.run_rule(ECOG)["state"])
        self.assertEqual("MET", self.run_rule({**ECOG, "values": [0, 2]})["state"])
        self.assertEqual("MET", self.run_rule({"fact": "ecog", "op": "le", "value": 2})["state"])

    def test_boolean_missingness(self):
        too_young = {"fact": "age", "op": "lt", "value": 18}
        for expr, state in (
            ({"any": [AGE, ECOG]}, "MET"), ({"all": [AGE, ECOG]}, "MISSING_DATA"),
            ({"any": [too_young, ECOG]}, "MISSING_DATA"),
            ({"all": [ECOG, {"any": [too_young]}]}, "NOT_MET"),
        ):
            with self.subTest(expr=expr):
                self.assertEqual(state, self.run_rule(expr)["state"])

    def test_patient_encounter_document_and_version_provenance(self):
        observation = add(self.bundle, "ecog", 1)
        result = self.run_rule(ECOG, patient="Patient/demo", encounter="Encounter/screen")
        self.assertEqual("MET", result["state"])
        self.assertEqual({"Patient/demo/_history/1", "Encounter/screen/_history/1",
                          "DocumentReference/doc2/_history/1", "Observation/obs2/_history/1"},
                         set(result["evidence"]))
        for key, value in (
            ("subject", {"reference": "Patient/other"}),
            ("encounter", {"reference": "Encounter/other"}),
            ("derivedFrom", [{"reference": "DocumentReference/doc2/_history/2"}]),
            ("issued", "2026-05-02T10:00:00Z"), ("effectiveDateTime", "2026-05-02T10:00:00Z"),
            ("code", {"coding": [{"system": "urn:local", "code": "89247-1"}]}),
            ("status", "preliminary"), ("valueInteger", True), ("valueInteger", -1),
        ):
            with self.subTest(field=key, value=value):
                original = observation[key]
                observation[key] = value
                self.assertEqual("MISSING_DATA", self.run_rule(ECOG)["state"])
                observation[key] = original
        for extra, value in (("valueString", "1"), ("effectivePeriod", {})):
            observation[extra] = value
            self.assertEqual("MISSING_DATA", self.run_rule(ECOG)["state"])
            del observation[extra]
        self.assertEqual("MISSING_DATA", self.run_rule(AGE, study="another-study")["state"])
        self.assertEqual("MISSING_DATA", self.run_rule(AGE, as_of="2026-05-01")["state"])

    def test_demographics_and_source_visibility(self):
        patient = self.bundle["entry"][0]["resource"]
        for birth in ("2008", "2008-03", "2008-02-30", "2028-05-01"):
            with self.subTest(birth=birth):
                patient["birthDate"] = birth
                self.assertEqual("MISSING_DATA", self.run_rule(AGE)["state"])
        patient["birthDate"] = "2008-05-01"
        patient["meta"]["lastUpdated"] = "2026-05-02T19:00:00Z"
        self.assertEqual("MISSING_DATA", self.run_rule(AGE)["state"])

    def test_age_uses_encounter_start_date_in_its_recorded_offset(self):
        patient = self.bundle["entry"][0]["resource"]
        visit = self.bundle["entry"][1]["resource"]
        # The birthday passes between screening and the later snapshot cutoff.
        patient["birthDate"] = "2008-05-02"
        self.assertEqual("NOT_MET", self.run_rule(AGE, as_of="2026-05-03T14:00:00Z")["state"])
        # It is still April 30 at the screening site, although already May 1 UTC.
        patient["birthDate"] = "2008-05-01"
        visit["period"]["start"] = "2026-04-30T22:30:00-04:00"
        self.assertEqual("NOT_MET", self.run_rule(AGE)["state"])
        # The same UTC day may also be the next calendar day at a site east of UTC.
        visit["period"]["start"] = "2026-05-02T01:00:00+10:00"
        patient["birthDate"] = "2008-05-02"
        self.assertEqual("MET", self.run_rule(AGE)["state"])

    def test_out_of_scope_ecog_cannot_invalidate_documented_screening_evidence(self):
        add(self.bundle, "ecog", 1)
        extra = add(self.bundle, "ecog", 2, minute=1)
        extra["dataAbsentReason"] = {"text": "no reported score"}
        extra["code"]["coding"].append({"system": "http://loinc.org", "code": "OTHER"})
        self.assertEqual("MISSING_DATA", self.run_rule(ECOG)["state"])
        for field, value in (
            ("issued", "2026-05-02T11:00:00Z"),
            ("effectiveDateTime", "2026-05-02T11:00:00Z"),
            ("effectiveDateTime", "2026-05-01T08:59:59Z"),
            ("encounter", {"reference": "Encounter/elsewhere"}),
            ("subject", {"reference": "Patient/someone-else"}),
        ):
            with self.subTest(field=field, value=value):
                original = extra[field]
                extra[field] = value
                result = self.run_rule(ECOG)
                self.assertEqual("MET", result["state"])
                self.assertNotIn("Observation/obs4/_history/1", result["evidence"])
                extra[field] = original

    def test_conflicting_and_repeat_measurements(self):
        add(self.bundle, "ecog", 1)
        add(self.bundle, "ecog", 1, minute=1)
        self.assertEqual("MET", self.run_rule(ECOG)["state"])
        add(self.bundle, "ecog", 2, minute=2)
        result = self.run_rule(ECOG)
        self.assertEqual("MISSING_DATA", result["state"])
        self.assertIn("conflicting", result["reason"])
        self.assertEqual(3, len([r for r in result["evidence"] if r.startswith("Observation/")]))

    def test_leap_day_decision_only_held_if_convention_changes_result(self):
        self.bundle["entry"][0]["resource"]["birthDate"] = "2008-02-29"
        for entry in self.bundle["entry"]:
            entry["resource"]["meta"]["lastUpdated"] = "2026-02-28T08:00:00Z"
        visit = self.bundle["entry"][1]["resource"]
        visit["period"] = {"start": "2026-02-28T08:00:00Z"}
        cutoff = "2026-02-28T15:00:00Z"
        self.assertEqual("AUTHORING_HOLD", self.run_rule(AGE, as_of=cutoff)["state"])
        expr = {"any": [AGE, {"fact": "age", "op": "lt", "value": 18}]}
        self.assertEqual("MET", self.run_rule(expr, as_of=cutoff)["state"])


if __name__ == "__main__":
    unittest.main()
