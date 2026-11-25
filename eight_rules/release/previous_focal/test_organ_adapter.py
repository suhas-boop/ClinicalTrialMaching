"""Native R4 research-profile fixtures for 106S01 organ rules, executable offline."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

import normalized as n
import organ_adapter as organ


def resource(packet, kind, ident=None):
    return next(e["resource"] for e in packet["bundle"]["entry"]
                if e["resource"]["resourceType"]==kind and (ident is None or e["resource"]["id"]==ident))


def run_checks(rules):
    checks=[]
    missing="MISSING_DATA"
    def run(cid, name, expected, mutate=None, inspect=None):
        packet=organ.example(rules,cid)
        if mutate:
            mutate(packet)
        rule=rules.get(cid) or rules["106S01-"+cid]
        snap=n.Snapshot(packet["bundle"],packet["context"])
        snap.native=organ.derive(rules,packet["bundle"],packet["context"])
        result=n.evaluate(rule,snap)
        assert result["state"]==expected,(name,expected,result["state"],result.get("reason"))
        if inspect:
            inspect(snap,rule,result)
        checks.append({"criterion":cid,"case":name,"expected":expected,"actual":result["state"]})

    def change(kind, ident=None, **props):
        return lambda p:resource(p,kind,ident).update(props)
    def quantity(key,value):
        return lambda p:resource(p,"Observation",key)["valueQuantity"].update(value=value)
    def add_clone(p, kind, ident, new_ident, **props):
        original=deepcopy(resource(p,kind,ident))
        original.update(id=new_ident,**props)
        p["bundle"]["entry"].append({"resource":original})
    def collection(p,key,when):
        resource(p,"Observation",key)["effectiveDateTime"]=when
        resource(p,"Specimen",key+"-spec")["collection"]["collectedDateTime"]=when
    def anchor_plan(p, occurrence, replace):
        reference=lambda x:{"reference":x}
        r=resource(p,"MedicationAdministration")
        d=deepcopy(resource(p,"DocumentReference","report-first-dose"))
        d.update(id="plan-source",date="2026-05-05T10:00:00Z")
        sr={"resourceType":"ServiceRequest","id":"signed-plan","meta":deepcopy(r["meta"]),
            "identifier":[{"system":organ.LOCAL,"value":"signed-order"}],"status":"active","intent":"order",
            "code":{"coding":[{"system":organ.LOCAL,"code":"c1d1-sot106"}]},"subject":r["subject"],
            "encounter":r["context"],"requester":reference("Organization/demo-site"),"occurrenceDateTime":occurrence,
            "authoredOn":"2026-05-04T15:00:00Z","supportingInfo":[reference(n.ref(d))]}
        if replace:
            p["bundle"]["entry"]=[e for e in p["bundle"]["entry"] if e["resource"] is not r]
        p["bundle"]["entry"].extend([{"resource":d},{"resource":sr}])

    def traces(all_keys, required, expected_values=None):
        def inspect(snap,rule,result):
            for key in all_keys:
                val,issue,refs,_=snap.native[n.contract(rule["facts"][key])]
                assert issue is None and set(required)<=set(refs) and all("/_history/" in r for r in refs),(key,refs)
                if expected_values and key in expected_values:
                    assert val==expected_values[key],(key,val)
        return inspect

    dose="MedicationAdministration/first-dose/_history/1"
    consent="Procedure/consent-event/_history/1"
    run("I14","echo at the inclusive 50 percent threshold","MET",inspect=traces(
        ["lvef","modality","lvef_screen"],[dose,consent,"DocumentReference/report-first-dose/_history/1",
        "DocumentReference/report-signed/_history/1","Observation/lvef/_history/1","DocumentReference/report-lvef/_history/1"],
        {"lvef":50,"modality":"ECHO","lvef_screen":True}))
    run("I14","below the ejection fraction threshold","NOT_MET",quantity("lvef",49.9))
    run("I14","MUGA value uses the same scan and units","MET",change("Observation","lvef",method={"coding":[{"system":organ.METHOD,"code":"MUGA"}]}))
    for name,mutate in [
        ("missing imaging method",change("Observation","lvef",method={})),
        ("unsupported imaging method",change("Observation","lvef",method={"coding":[{"system":organ.METHOD,"code":"MRI"}]})),
        ("incompatible percentage representation",lambda p:resource(p,"Observation","lvef")["valueQuantity"].update(code="1")),
        ("nonfinite numerical result",quantity("lvef",float("nan"))),
        ("above possible percent",quantity("lvef",101)),
        ("future result unavailable",change("Observation","lvef",issued="2026-05-14T12:00:00Z")),
        ("wrong study encounter",change("Observation","lvef",encounter={"reference":"Encounter/other"})),
        ("wrong patient",change("Observation","lvef",subject={"reference":"Patient/other"})),
        ("source superseded",change("DocumentReference","report-lvef",status="superseded")),
        ("two measurements cannot silently cross-bind",lambda p:add_clone(p,"Observation","lvef","lvef2",valueQuantity={"value":40,"code":"%","system":organ.UCUM})),
        ("signature missing",change("Procedure","consent-event",status="not-done")),
        ("no demonstrable order at identical consent and scan times",change("Observation","lvef",effectiveDateTime="2026-05-01T09:00:00Z")),
        ("assessment before signature",change("Observation","lvef",effectiveDateTime="2026-05-01T08:59:59Z")),
        ("signed and actual C1D1 disagree",lambda p:anchor_plan(p,"2026-05-15T09:00:00Z",False)),
        ("unknown study administrator",change("MedicationAdministration","first-dose",performer=[{"actor":{"reference":"PractitionerRole/other"}}])),
        ("screening duration exceeds 21 days",change("Procedure","consent-event",performedDateTime="2026-04-01T09:00:00Z")),
    ]:
        run("I14",name,missing,mutate)
    run("I14","prospective signed scheduling anchor","MET",lambda p:anchor_plan(p,"2026-05-15T09:00:00Z",True),
        traces(["lvef"],["ServiceRequest/signed-plan/_history/1","DocumentReference/plan-source/_history/1"]))

    ptfields=["pt","pt_col_days","pt_result_days","pt_screen"]
    run("I11","both laboratory ratios at the inclusive boundary","MET",inspect=traces(ptfields,
        [dose,consent,"Observation/pt/_history/1","DocumentReference/report-pt/_history/1",
         "Specimen/pt-spec/_history/1","Communication/receipt-pt/_history/1"],
        {"pt":1.5,"pt_col_days":6,"pt_result_days":5,"pt_screen":True}))
    run("I11","discordant PT and INR retain protocol hold","AUTHORING_HOLD",quantity("pt",18.01))
    def both_high(p):
        quantity("pt",18.1)(p)
        quantity("inr",1.51)(p)
    run("I11","both PT and INR above threshold","NOT_MET",both_high)
    run("I11","collection on day minus seven", "MET", lambda p:collection(p,"pt","2026-05-05T09:00:00Z"))
    run("I11","collection on day minus eight", missing, lambda p:collection(p,"pt","2026-05-04T09:00:00Z"))
    def local_midnight(p):
        p["context"]["site_zone"]="America/Los_Angeles"
        collection(p,"pt","2026-05-05T01:00:00Z")
    run("I11","collection calendar follows the site timezone",missing,local_midnight)
    for name,mutate in [
        ("site receipt cannot be inferred from issued date",change("Communication","receipt-pt",payload=[])),
        ("site receipt refers to a different result",change("Communication","receipt-pt",payload=[{"contentReference":{"reference":"DocumentReference/other/_history/1"}}])),
        ("receipt precedes report release",change("Communication","receipt-pt",received="2026-05-07T12:00:00Z")),
        ("receipt on dosing day",change("Communication","receipt-pt",received="2026-05-12T09:00:00Z")),
        ("conditional reference interval requires adjudication",change("Observation","pt",referenceRange=[{"text":"adult males","high":{"value":12,"code":"s","system":organ.UCUM}}])),
        ("upper limit missing",change("Observation","pt",referenceRange=[])),
        ("upper limit uses different units",lambda p:resource(p,"Observation","pt")["referenceRange"][0]["high"].update(code="min")),
        ("zero upper limit",lambda p:resource(p,"Observation","pt")["referenceRange"][0]["high"].update(value=0)),
        ("PT code requires plasma",change("Specimen","pt-spec",type={"coding":[{"system":organ.MATERIAL,"code":"SER"}]})),
        ("specimen belongs to another patient",change("Specimen","pt-spec",subject={"reference":"Patient/other"})),
        ("preliminary result",change("Observation","pt",status="preliminary")),
        ("two inbox receipts require reconciliation",lambda p:add_clone(p,"Communication","receipt-pt","second-receipt")),
    ]:
        run("I11",name,missing,mutate)
    run("I10","ordinary limits for total bilirubin and both transaminases","MET",inspect=traces(
        ["tb","tb_col_days","tb_result_days","tb_screen"],
        ["Observation/tb/_history/1","DocumentReference/report-tb/_history/1","Specimen/tb-spec/_history/1",
         "Communication/receipt-tb/_history/1",dose,consent],{"tb":1.5}))
    run("I10","ALT exceeds even the liver-involvement allowance","NOT_MET",quantity("alt",141))
    run("I10","bilirubin exceeds even the Gilbert allowance","NOT_MET",quantity("tb",3.1))
    run("I10","ordinary low bilirubin requires its own serum specimen",missing,change("Specimen","tb-spec",subject={"reference":"Patient/other"}))
    def disable(p):
        rule=rules.get("I14") or rules["106S01-I14"]
        p["context"]["enabled_contracts"].remove(n.contract(rule["facts"]["lvef"]))
    run("I14","disabled LVEF mapping cannot supply verdict","BINDING_HOLD",disable)
    def incompatible_bilirubin(p):
        obs=resource(p,"Observation","tb")
        obs["valueQuantity"]["code"]="umol/L"
        obs["referenceRange"][0]["high"]["code"]="umol/L"
    run("I10","mass concentration codes reject molar units",missing,incompatible_bilirubin)
    return checks


def rules_for_tests():
    base=Path(__file__).resolve().parent
    for path in (base/"rules.json",base/"sotio_rules.json",base.parent/"authoring/organ/rules.json"):
        if path.exists():
            data=json.loads(path.read_text())
            data=data.get("rules",data)
            if isinstance(data,dict) and ("I14" in data or "106S01-I14" in data):
                return data
    raise FileNotFoundError("Provide SOTIO rule definitions to run_checks(rules).")


class NativeOrganTests(unittest.TestCase):
    def test_source_linked_measurements(self):
        self.assertTrue(run_checks(rules_for_tests()))


if __name__=="__main__":
    print(json.dumps(run_checks(rules_for_tests()),indent=2))
