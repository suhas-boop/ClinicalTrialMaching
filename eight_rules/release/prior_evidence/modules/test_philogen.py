"""Synthetic FHIR replay and boundary controls. Run with python test_philogen.py."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
from philogen import CODES, LIVER, LOINC, RULES, STUDY, STUDY_SYSTEM, UCUM, VERSION, evaluate, ref

BASE = datetime(2026,1,30,12,0,0,tzinfo=timezone.utc)
def stamp(days=0, hours=0):
    return (BASE+timedelta(days=days,hours=hours)).isoformat()

def mk(kind,key,time=None,**fields):
    return dict(resourceType=kind,id=key,meta={"versionId":"1","lastUpdated":time or stamp(-1)},**fields)

def time_scope(a):
    return "|".join(a[k] for k in ("patient","encounter","consent_signed","screening_start","screening_end",
                                   "randomization","first_dose"))
def example(rule="I05", *, day=-2, dose_day=3, encounter_start=-9, consent_day=-10,
            value=None, uln=1.2, historic=False):
    p={"reference":"Patient/synthetic"}
    performer={"reference":"Practitioner/demo"}
    trial=[{"system":STUDY_SYSTEM,"value":STUDY+"|"+VERSION}]
    when=stamp(day)
    enc=mk("Encounter","screen",stamp(),identifier=trial,subject=p,status="finished",
           period={"start":stamp(encounter_start),"end":stamp(0,-1)})
    def doc(key,time):
        return mk("DocumentReference",key,time,date=time,subject=p,status="current",docStatus="final",
                  author=[performer],identifier=trial,content=[{"attachment":{"title":"Synthetic study record"}}])
    timeline=doc("anchors",stamp(8))
    report=doc("report",when)
    a={"study":STUDY,"version":VERSION,"purpose":"historical_synthetic_replay","patient":p["reference"],
       "encounter":ref(enc),"anchor_mode":"verified_actual","consent_signed":stamp(consent_day),
       "screening_start":stamp(encounter_start),"screening_end":stamp(0,-1),"randomization":stamp(),
       "first_dose":stamp(dose_day),"as_of":stamp(9)}
    a["anchor_attestation"]={"reference":ref(timeline),"purpose":"actual-screening-anchors",
                             "signer":performer["reference"],"scope":time_scope(a),"signature_verified":True}
    o=mk("Observation","measure",when,subject=p,status="final",code={"coding":[{"system":LOINC,"code":next(iter(LIVER)) if rule=="E10" else CODES[rule]}]},
         effectiveDateTime=when,issued=when,derivedFrom=[{"reference":ref(report)}],
         encounter={"reference":"Encounter/screen"})
    sp=mk("Specimen","tube",when,status="available",subject=p,type={"coding":[{
          "system":"http://terminology.hl7.org/CodeSystem/v2-0487","code":"PPP"}]})
    if rule=="I05":
        o["valueInteger"]=1 if value is None else value
    else:
        o["valueQuantity"]={"value":(50 if rule=="E15" else 1.8) if value is None else value,"system":UCUM,
                            "code":"%" if rule=="E15" else "{INR}"}
        if rule=="E11":
            o["referenceRange"]=[{"high":{"value":uln,"system":UCUM,"code":"{INR}"}}]
            o["specimen"]={"reference":ref(sp)}
    items=[enc,timeline,report,o,sp]
    if rule=="E10":
        sp["type"]["coding"][0]["code"]="SER"
        for index,concept in enumerate(LIVER):
            assay=o if index==0 else deepcopy(o)
            assay["code"]["coding"][0]["code"]=concept
            assay["id"]="liver-"+concept
            unit="mg/dL" if concept=="1975-2" else "U/L"
            assay["valueQuantity"]={"value":1,"system":UCUM,"code":unit}
            assay["referenceRange"]=[{"high":{"value":1,"system":UCUM,"code":unit}}]
            assay["specimen"]={"reference":ref(sp)}
            if index:items.append(assay)
    if historic:
        o["encounter"]={"reference":"Encounter/routine-care"}
        suitable=doc("sufficient",stamp(-1))
        items.append(suitable)
        a["historical_echo"]={ref(o):{"purpose":"pre-consent-echo-sufficient", "scope":ref(o),
                              "reference":ref(suitable),"signer":performer["reference"],"signature_verified":True}}
    return {"resourceType":"Bundle","type":"collection","entry":[{"resource":r} for r in items]},a

def run_checks():
    out=[]
    def trial(rule,label,expect,fx=None,**opts):
        bundle,a=example(rule,**opts)
        obs=next(e['resource'] for e in bundle['entry'] if e['resource']['resourceType']=='Observation')
        if fx:
            fx(bundle,a,obs)
        r=evaluate(rule,bundle,a)
        out.append({"criterion":rule,"case":label,"expected":expect,"actual":r["state"]})
        if expect in {"MET","NOT_MET"}:
            assert len(r["evidence"]) >= 4 and all("/_history/" in x for x in r["evidence"])
        return r
    def cc(k,v):
        return lambda b,a,o:a.update({k:v})
    def oo(k,v):
        return lambda b,a,o:o.update({k:v})
    def remove(k):
        return lambda b,a,o:o.pop(k,None)
    def alter_type(kind, field, value):
        def f(b,a,o):
            r=next(e["resource"] for e in b["entry"] if e["resource"]["resourceType"]==kind)
            r[field]=value
        return f
    def conflict(b,a,o):
        other=deepcopy(o)
        other["id"]="other"
        if "valueInteger" in other:other["valueInteger"]=4
        elif "referenceRange" in other:other["valueQuantity"]["value"]=4
        else:other["valueQuantity"]["value"]=30
        b["entry"].append({"resource":other})
    for rule in CODES:
        trial(rule,"baseline inclusive boundary","MET")
        trial(rule,"no observations","MISSING_DATA",lambda b,a,o:b["entry"].remove({"resource":o}))
        trial(rule,"current v7 rejected","REVIEW_REQUIRED",cc("version","7.0"))
        trial(rule,"clinical release rejected","REVIEW_REQUIRED",cc("purpose","live_screening"))
        trial(rule,"planned dates cannot replace actual anchors","MISSING_DATA",cc("anchor_mode","planned"))
        trial(rule,"unverified anchor signature","MISSING_DATA",
              lambda b,a,o:a["anchor_attestation"].update(signature_verified=False))
        trial(rule,"patient changed on normalized anchor only","MISSING_DATA",cc("patient","Patient/x"))
        trial(rule,"verified report for another patient","MISSING_DATA",
              lambda b,a,o:next(e["resource"] for e in b["entry"] if e["resource"]["id"]=="report").update(subject={"reference":"Patient/other"}))
        trial(rule,"wrong observation patient","MISSING_DATA",oo("subject",{"reference":"Patient/other"}))
        trial(rule,"unexpected screening encounter","MISSING_DATA",oo("encounter",{"reference":"Encounter/other"}))
        trial(rule,"wrong source report version","MISSING_DATA",oo("derivedFrom",[{"reference":"DocumentReference/report/_history/2"}]))
        trial(rule,"results conflicting across threshold","MISSING_DATA",conflict)
        trial(rule,"preliminary observation","MISSING_DATA",oo("status","preliminary"))
        trial(rule,"issued after randomization","MISSING_DATA",oo("issued",stamp(1)))
        trial(rule,"first dose too late","MISSING_DATA",dose_day=8)
        trial(rule,"before consent without accepted instrument","MISSING_DATA",day=-13)
        trial(rule,"exact 14d before randomization / 21d before treatment","MET",day=-14,dose_day=7,encounter_start=-14,consent_day=-15)
        trial(rule,"15d before randomization","MISSING_DATA",day=-15,encounter_start=-15,consent_day=-16)
    trial("I05","ECOG 0","MET",value=0)
    trial("I05","ECOG 2","NOT_MET",value=2)
    trial("I05","invalid ECOG -1","MISSING_DATA",value=-1)
    trial("E11","INR 1.79 with ULN 1.2","MET",value=1.79,uln=1.2)
    trial("E11","INR 1.81 with ULN 1.2","NOT_MET",value=1.81,uln=1.2)
    trial("E11","no ULN","MISSING_DATA",remove("referenceRange"))
    trial("E11","zero ULN","MISSING_DATA",uln=0)
    trial("E11","conditional ULN","MISSING_DATA",
          lambda b,a,o:o["referenceRange"][0].update(appliesTo=[{"text":"unspecified"}]))
    trial("E11","missing specimen","MISSING_DATA",remove("specimen"))
    trial("E11","serum instead of platelet-poor plasma","MISSING_DATA",alter_type("Specimen","type",{"coding":[
          {"system":"http://terminology.hl7.org/CodeSystem/v2-0487","code":"SER"}]}))
    trial("E11","PT seconds instead of INR","MISSING_DATA",lambda b,a,o:o["valueQuantity"].update(code="s"))
    trial("E15","LVEF 49.9%","NOT_MET",value=49.9)
    trial("E15","LVEF 52%","MET",value=52)
    trial("E15","unverified fraction unit","MISSING_DATA",lambda b,a,o:o["valueQuantity"].update(code="1"))
    trial("E15","unspecified imaging method","MISSING_DATA",oo("code",{"coding":[{"system":LOINC,"code":"10230-1"}]}))
    trial("E15","28-day pre-consent ECHO with signed sufficiency","MET",day=-28,historic=True)
    trial("E15","29-day pre-consent ECHO","MISSING_DATA",day=-29,historic=True)
    trial("E15","unknown pre-consent echo suitability","MISSING_DATA",day=-20)
    trial("E15","suitability attests to unrelated ECHO","MISSING_DATA",
          lambda b,a,o:a["historical_echo"][ref(o)].update(scope="Observation/wrong/_history/1"),day=-20,historic=True)
    def assay(b,code):
        return next(e["resource"] for e in b["entry"] if e["resource"]["id"]=="liver-"+code)
    def only(b,code):
        b["entry"]=[e for e in b["entry"] if e["resource"]["resourceType"]!="Observation"
                    or e["resource"]["id"]=="liver-"+code]
    trial("E10","all five below their ULNs","MET")
    for concept in LIVER:
        trial("E10","equality excludes for "+concept,"NOT_MET",
              lambda b,a,o,c=concept:assay(b,c)["valueQuantity"].update(value=1.5))
    trial("E10","higher local bilirubin ULN changes comparison","MET",
          lambda b,a,o:(assay(b,"1975-2")["valueQuantity"].update(value=1.9),
                        assay(b,"1975-2")["referenceRange"][0]["high"].update(value=1.4)))
    trial("E10","one normal assay cannot clear the panel","MISSING_DATA",
          lambda b,a,o:only(b,"1975-2"))
    trial("E10","one definite elevation excludes despite missing other assays","NOT_MET",
          lambda b,a,o:(only(b,"1975-2"),assay(b,"1975-2")["valueQuantity"].update(value=3)))
    trial("E10","total bilirubin cannot be replaced by another analyte","MISSING_DATA",
          lambda b,a,o:assay(b,"1975-2")["code"]["coding"][0].update(code="unknown"))
    trial("E10","incompatible ULN units","MISSING_DATA",
          lambda b,a,o:assay(b,"1975-2")["referenceRange"][0]["high"].update(code="U/L"))
    trial("E10","conditional upper reference intervals","MISSING_DATA",
          lambda b,a,o:assay(b,"1920-8")["referenceRange"][0].update(age={"low":{"value":65}}))
    trial("E10","unverified specimen","MISSING_DATA",
          lambda b,a,o:o.update(specimen={"reference":"Specimen/nope/_history/1"}))
    trial("E10","labs cannot use the pre-consent instrument exception","MISSING_DATA",day=-20)
    trial("E10","active protocol blocked","REVIEW_REQUIRED",cc("version","7.0"))
    trial("E10","paper/chart standardization gate closed","MISSING_DATA",
          lambda b,a,o:a["anchor_attestation"].update(signature_verified=False))
    return out


class PhilogenChecks(unittest.TestCase):
    def test_expected_states(self):
        for c in run_checks():
            with self.subTest(criterion=c["criterion"],case=c["case"]):
                self.assertEqual(c["expected"],c["actual"])


if __name__=="__main__":
    print(json.dumps(run_checks(),indent=2))
    unittest.main(argv=["philogen"],exit=True)
