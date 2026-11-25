from copy import deepcopy
from datetime import date,timedelta
from runpy import run_path
import unittest

from native_lab import replay, ROOT, M, UCUM
from narrative_evidence import extract
from screen_vignette import evaluate_vignette
from evidence_review import work_counts

DAY=date(2026,5,1)
O={"resourceType":"Observation","id":"p1","subject":{"reference":"Patient/demo"},"status":"final",
   "effectiveDateTime":str(DAY),"category":[{"coding":[{"system":"http://terminology.hl7.org/CodeSystem/observation-category","code":"laboratory"}]}],
   "code":{"coding":[{"system":"http://loinc.org","code":"26515-7"}]},
   "valueQuantity":{"system":UCUM,"code":"10*3/uL","value":99,"unit":"K/uL"}}
D={"resourceType":"DiagnosticReport","id":"lab","subject":{"reference":"Patient/demo"},"status":"final",
   "category":[{"coding":[{"system":"http://terminology.hl7.org/CodeSystem/v2-0074","code":"LAB"}]}],
   "effectiveDateTime":"2026-05-01T10:00:00Z","issued":"2026-05-01T11:00:00Z","result":[{"reference":"Observation/p1"}]}

class NativeLabTests(unittest.TestCase):
    def setUp(self):
        self.o,self.d=deepcopy(O),deepcopy(D)
        self.rows=[self.o,self.d]
    def result(self,**kw):
        return replay(self.rows,"Patient/demo",DAY,**({"simulate":True}|kw))
    def test_missing_anchor(self):
        self.assertEqual(self.result(simulate=False)["full_criterion"],"MISSING_DATA")
    def test_full_fail(self):
        t=self.result()
        self.assertEqual((t["platelet_clause"],t["full_criterion"]),("NOT_MET","NOT_MET"))
        self.assertEqual(len(t["decision_evidence"]),2)
        self.assertEqual(t["work"]["human_questions"],0)
        self.assertEqual(t["remaining_requests"],[])
    def test_boundary_does_not_clear_panel(self):
        self.o["valueQuantity"]["value"]=100
        t=self.result()
        self.assertEqual((t["platelet_clause"],t["full_criterion"]),("MET","MISSING_DATA"))
    def test_alias_opt_in(self):
        self.o["valueQuantity"]={"value":98,"unit":"Thousand/uL"}
        self.assertEqual(self.result()["platelet_clause"],"MISSING_DATA")
        self.assertEqual(self.result(local=True)["platelet_clause"],"NOT_MET")
    def test_unacceptable_results(self):
        for field,val in [("unit","/uL"),("code","g/L"),("system","local"),("comparator","<"),("value",-1),("value",True)]:
            self.o["valueQuantity"]=deepcopy(O["valueQuantity"])
            self.o["valueQuantity"][field]=val
            with self.subTest(field=field):
                self.assertEqual(self.result()["platelet_clause"],"MISSING_DATA")
    def test_conflicting_or_nonnumeric_type(self):
        self.o["valueString"]="many"
        self.assertEqual(self.result()["platelet_clause"],"MISSING_DATA")
    def test_wrong_patient(self):
        self.d["subject"]={"reference":"Patient/b"}
        self.assertEqual(self.result()["platelet_clause"],"MISSING_DATA")
    def test_status(self):
        for obj in self.rows:
            obj["status"]="entered-in-error"
            self.assertEqual(self.result()["platelet_clause"],"MISSING_DATA")
            obj["status"]="final"
    def test_missing_report_then_valid_link(self):
        self.d["result"][0]["reference"]="Observation/unlinked"
        self.assertEqual(self.result()["platelet_clause"],"MISSING_DATA")
        self.d["result"][0]["reference"]="Observation/p1/_history/2"
        self.assertEqual(self.result()["platelet_clause"],"MISSING_DATA")
        self.o["meta"]={"versionId":"2"}
        self.assertEqual(self.result()["platelet_clause"],"NOT_MET")
    def test_wrong_analyte_or_specimen(self):
        self.o["code"]["coding"].append({"system":"http://loinc.org","code":"different"})
        self.assertEqual(self.result()["platelet_clause"],"MISSING_DATA")
        self.o["code"]=deepcopy(O["code"])
        self.o["specimen"]={"reference":"Specimen/ambiguous"}
        self.assertEqual(self.result()["platelet_clause"],"MISSING_DATA")
    def test_distinct_quantities_and_duplicate_delivery(self):
        self.assertEqual(replay(self.rows*2,"Patient/demo",DAY,True),self.result())
        other=deepcopy(self.o);other["valueQuantity"]["value"]=118
        self.rows.append(other)
        self.assertEqual(self.result()["platelet_clause"],"MISSING_DATA")
        other["id"]="another"
        self.d["result"].append({"reference":"Observation/another"})
        self.assertEqual(self.result()["platelet_clause"],"MISSING_DATA")
    def test_publication_and_replay(self):
        self.d["issued"]="2026-05-02T09:00:00Z"
        self.assertEqual(self.result()["platelet_clause"],"MISSING_DATA")
        self.assertEqual(self.result(as_of=self.d["issued"])["full_criterion"],"NOT_MET")
    def test_report_after_simulated_start(self):
        self.d["issued"]="2026-05-09T08:00:00Z"
        self.assertEqual(self.result(as_of=self.d["issued"])["full_criterion"],"MISSING_DATA")

    def test_wrong_explicit_unit_or_early_observation_issue(self):
        self.o["valueQuantity"]["unit"]="g/L"
        self.assertEqual(self.result()["full_criterion"],"MISSING_DATA")
        self.o["valueQuantity"]=deepcopy(O["valueQuantity"])
        self.o["issued"]="2026-04-30T20:00:00Z"
        self.assertEqual(self.result()["full_criterion"],"MISSING_DATA")

    def test_window_edges(self):
        self.o["effectiveDateTime"]="2026-04-30"
        self.d["effectiveDateTime"]="2026-04-30T10:00:00Z"
        self.assertEqual(self.result()["platelet_clause"],"MISSING_DATA")
        self.o["effectiveDateTime"]="2026-05-08"
        self.d["effectiveDateTime"]=self.d["issued"]="2026-05-08T10:00:00Z"
        self.assertEqual(self.result(as_of=self.d["issued"])["platelet_clause"],"MISSING_DATA")
    def test_anchor(self):
        fixture=run_path(str(ROOT/"prior_evidence/modules/duality_qtc.py"))["example"]()
        c=fixture["context"];c["protocol_sha256"]=M["protocol_sha256"]
        for r in self.rows:r["encounter"]={"reference":c["encounter"]}
        t=self.result(simulate=False,anchor_packet=fixture,as_of=c["as_of"])
        self.assertEqual((t["mode"],t["full_criterion"]),("documented_planned_c1d1","NOT_MET"))
        self.assertIn(c["first_dose_ref"],t["decision_evidence"])
        c["patient"]="Patient/other"
        with self.assertRaises(ValueError):self.result(simulate=False,anchor_packet=fixture,as_of=c["as_of"])
    def test_actual_c1d1_administration(self):
        module=run_path(str(ROOT/"prior_evidence/modules/duality_qtc.py"))
        fixture=module["example"]()
        c=fixture["context"];c["protocol_sha256"]=M["protocol_sha256"]
        order=next(e["resource"] for e in fixture["bundle"]["entry"] if e["resource"]["id"]=="first")
        order.update(resourceType="MedicationAdministration",status="completed",
                     effectiveDateTime="2026-05-06T15:00:00Z",
                     medicationCodeableConcept={"coding":[{"system":module["LOCAL"],"code":"DB-1311"}]},
                     identifier=[{"system":module["STUDY_SYSTEM"],"value":M["study"]},
                                 {"system":module["LOCAL"]+":event","value":"c1d1-first-dose"}])
        c["first_dose_ref"]="MedicationAdministration/first/_history/1"
        for r in self.rows:r["encounter"]={"reference":c["encounter"]}
        result=self.result(simulate=False,anchor_packet=fixture,as_of=c["as_of"])
        self.assertEqual((result["mode"],result["full_criterion"]),("documented_actual_c1d1","NOT_MET"))
        self.assertIn(c["first_dose_ref"],result["decision_evidence"])

    def test_vital_units_and_qualifiers(self):
        for line in ["Tachycardic and tachypneic.","HR: 98","Target HR: 98 bpm.","Father's HR: 98 bpm.","HR: 90-110 bpm."]:
            self.assertNotIn("heart_rate",extract("0. "+line)["facts"])
        self.assertEqual(extract("0. BP: 60/30 mmHg, HR: 140/min.")["facts"]["heart_rate"]["value"],140)
        self.assertNotIn("heart_rate",extract("0. HR: 88 bpm.\n1. HR: 99 bpm.")["facts"])
    def test_vitals_reach_rule_and_route(self):
        import json
        rules=json.loads((ROOT.parents[1]/"nih_benchmark/round3/rules.json").read_text())
        for k,line,state in [("186","HR: 90 bpm.","MET"),("186","HR: 89 bpm.","NOT_MET"),
                             ("187","RR: 20/min.","MET"),("187","RR: 19/min.","MISSING_DATA")]:
            r=evaluate_vignette(rules[k],"demo","dev","synthetic test", "0. "+line)
            self.assertEqual(r["state"],state)
    def test_distinct_metrics(self):
        q=[{"id":"abc","route":"protocol_review"}]*2+[{"id":"rec","route":"retrieve_record"}]
        self.assertEqual(work_counts({},q),{"human_questions":1,"record_lookups":1,"engineering_items":0,"evidence_backed_decisions":0})
