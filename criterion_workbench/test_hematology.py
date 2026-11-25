from copy import deepcopy
import unittest
from test_native_lab import O,D,DAY
from native_lab import replay


def lab(code,value,unit="10*3/uL",display="K/uL",rid="first"):
    o,d=deepcopy(O),deepcopy(D)
    o["id"]=rid
    o["code"]["coding"][0]["code"]=code
    o["valueQuantity"].update(value=value,code=unit,unit=display)
    d["id"]=rid
    d["result"]=[{"reference":"Observation/"+rid}]
    return [o,d]


def check(rows,**opts):
    return replay(rows,"Patient/demo",DAY,**({"simulate":True,"hematology":True}|opts))


class HematologyTests(unittest.TestCase):
    def test_thresh(self):
        for val,state in [(8.9,"NOT_MET"),(9,"MET"),(9.1,"MET")]:
            with self.subTest(val=val):
                t=check(lab("718-7",val,"g/dL","g/dL"))
                self.assertEqual(t["fields"]["hemoglobin"]["state"],state)
                self.assertEqual(t["full_criterion"],"NOT_MET" if val<9 else "MISSING_DATA")
    def test_conversion(self):
        t=check(lab("718-7",89,"g/L","g/L"))
        self.assertEqual(t["fields"]["hemoglobin"]["values"],[8.9])
    def test_anc_boundary(self):
        for val,state in [(1.499,"NOT_MET"),(1.5,"MET")]:
            self.assertEqual(check(lab("26499-4",val))["fields"]["anc"]["state"],state)
    def test_percentage_and_other_hb(self):
        for code,unit,key in [("26511-6","%","anc"),("28540-3","g/dL","hemoglobin")]:
            self.assertEqual(check(lab(code,5,unit,unit))["fields"][key]["state"],"MISSING_DATA")
    def test_unit_dimensions(self):
        t=check(lab("26499-4",1.0,"µL","µL"))
        self.assertEqual(t["fields"]["anc"]["state"],"MISSING_DATA")
    def test_all_pass_is_partial(self):
        t=check(lab("718-7",9,"g/dL","g/dL","hb")+lab("26499-4",1.5,rid="anc")+lab("26515-7",100,rid="plt"))
        self.assertEqual([f["state"] for f in t["fields"].values()],["MET"]*3)
        self.assertEqual(t["full_criterion"],"MISSING_DATA")
    def test_multiple_failing_values_preserve_all_refs(self):
        t=check(lab("26515-7",99)+lab("26515-7",82,rid="second"))
        self.assertEqual(t["fields"]["platelets"]["values"],[82000,99000])
        self.assertEqual(t["full_criterion"],"NOT_MET")
        self.assertEqual(len(t["decision_evidence"]),4)
    def test_cross_threshold_opens_one_protocol_question(self):
        rows=lab("26515-7",99)+lab("26515-7",100,rid="second")+lab("718-7",8,"g/dL","g/dL","hb")+lab("718-7",10,"g/dL","g/dL","hb2")
        t=check(rows)
        self.assertEqual(t["full_criterion"],"MISSING_DATA")
        self.assertEqual(len([q for q in t["requests"] if q["route"]=="protocol_review"]),1)
        self.assertEqual(check(rows+rows),t)
    def test_no_question_for_independently_decided_criterion(self):
        t=check(lab("26515-7",99)+lab("26515-7",100,rid="second")+lab("718-7",8,"g/dL","g/dL","hb"))
        self.assertEqual((t["full_criterion"],t["work"]["human_questions"]),("NOT_MET",0))
    def test_invalid_companion_prevents_consensus(self):
        t=check(lab("26515-7",99)+lab("26515-7",98,"g/dL","g/dL","second"))
        self.assertEqual(t["full_criterion"],"MISSING_DATA")
    def test_anchor_and_future_report(self):
        rows=lab("718-7",7,"g/dL","g/dL")
        self.assertEqual(check(rows,simulate=False)["full_criterion"],"MISSING_DATA")
        rows[1]["issued"]="2026-05-02T11:00:00Z"
        self.assertEqual(check(rows)["full_criterion"],"MISSING_DATA")
        self.assertEqual(check(rows,as_of=rows[1]["issued"])["full_criterion"],"NOT_MET")
