"""Reusable positive identity evidence on an as-of normalized R4 collection Bundle.

This is a leaf resolver. It does not decide eligibility, current line, regimen,
disease extent, grade or absence of other exposures. Context fields are study,
criterion, fact, patient (Patient/id), episode (Condition/id) and as_of (instant).
Run --self-test or --bundle FILE --context FILE. Codes are a small pinned research
subset of michigan-lms-three-criteria-r1; site-local-only codes remain unmapped.
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

CATALOG=json.loads(Path(__file__).with_name("identity_catalog.json").read_text())
RULES=[]
LEAVES=[
    {"study":"NCT05653388","criterion":"MI-LMS-01","fact":"documented_LMS_identity","source":"§2.1 bullet 1, DOCX paragraph 423CE7E7"},
    {"study":"NCT05653388","criterion":"MI-LMS-02","fact":"doxorubicin_administration_identity","source":"§2.1 bullet 2, DOCX paragraph 35996DFF"},
    {"study":"NCT05653388","criterion":"MI-LMS-02","fact":"gemcitabine_administration_identity","source":"§2.1 bullet 2, DOCX paragraph 35996DFF"},
    {"study":"NCT05653388","criterion":"MI-LMS-02","fact":"docetaxel_administration_identity","source":"§2.1 bullet 2, DOCX paragraph 35996DFF"},
    {"study":"PH-L19TNFDOX2","criterion":"I02","fact":"histological_LMS_identity","source":"Historical protocol v6 only, §4.1 #2 p.74"},
    {"study":"PH-L19TNFDOX2","criterion":"E04","fact":"doxorubicin_administration_identity","source":"Historical protocol v6 only, §4.2 #4. Positive doxorubicin example of the broader prior-anthracycline class."},
    {"study":"DB-1311-O-1001","criterion":"I17","fact":"docetaxel_administration_identity","source":"§5.1 #17 p.62, phase 2a cohort 4 only. This only establishes a docetaxel administration."},
]
DRUG={"doxorubicin_administration_identity":"3639","gemcitabine_administration_identity":"12574","docetaxel_administration_identity":"72962"}


def time(value):
    dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    if dt.utcoffset() is None: raise ValueError("Full offset-qualified timestamps are required.")
    return dt


def ref(r):
    v=r["meta"]["versionId"]
    if not isinstance(v,str) or not v or "/" in v: raise ValueError("Missing version.")
    return r["resourceType"]+"/"+r["id"]+"/_history/"+v


def codes(concept,system):
    return {v["code"] for v in concept.get("coding",[]) if v.get("system")==system}


def resolve(bundle,context):
    result={"study":context.get("study"),"criterion":context.get("criterion"),"fact":context.get("fact"),"full_criterion":False}
    def answer(state,reason,records=(),identities=()):
        return {**result,"state":state,"reason":reason,"evidence":sorted(set(records)),"identities":list(identities)}
    try:
        if not any(all(row[k]==result[k] for k in ("study","criterion","fact")) for row in LEAVES):
            raise ValueError("This fact is not a registered source-linked leaf.")
        p,ep,cutoff=context["patient"],context["episode"],time(context["as_of"])
        if bundle.get("type")!="collection" or bundle.get("resourceType")!="Bundle":raise ValueError("Provide a normalized collection Bundle.")
        resources={}
        for item in bundle["entry"]:
            r=item["resource"]
            if time(r["meta"]["lastUpdated"])>cutoff:continue
            key=r["resourceType"]+"/"+r["id"]
            if key in resources:raise ValueError("Choose one resource version per logical ID as of the run.")
            resources[key]=r
        episode=resources[ep]
        if resources[p]["resourceType"]!="Patient" or episode["resourceType"]!="Condition" or episode.get("subject",{}).get("reference")!=p:
            raise ValueError("Patient and target condition do not match.")
        if episode.get("modifierExtension") or episode.get("implicitRules") or time(episode["recordedDate"])>cutoff:
            raise ValueError("Verify episode provenance as of this run.")
        def source(link,kind):
            requested=link.get("reference","")
            record=resources.get(requested.split("/_history/")[0])
            if (not record or record.get("resourceType")!=kind or ref(record)!=requested or
                record.get("subject",{}).get("reference")!=p or record.get("modifierExtension") or record.get("implicitRules")):return None
            return record

        fact=result["fact"]
        if fact in DRUG:
            found=[]; evidence=[]; unmapped=False
            for r in resources.values():
                if r["resourceType"]!="MedicationAdministration" or r.get("subject",{}).get("reference")!=p or r.get("status")!="completed": continue
                if not any(l.get("reference") in (ep,ref(episode)) for l in r.get("reasonReference",[])):continue
                if r.get("modifierExtension") or r.get("implicitRules"):raise ValueError("Verify medication modifier semantics.")
                if "effectiveDateTime" in r and "effectivePeriod" not in r: end=time(r["effectiveDateTime"])
                elif "effectivePeriod" in r and "effectiveDateTime" not in r:
                    end=time(r["effectivePeriod"]["end"])
                    if "start" in r["effectivePeriod"] and time(r["effectivePeriod"]["start"])>end:raise ValueError("Invalid administration interval.")
                else:raise ValueError("Provide the dated completed administration.")
                if end>cutoff:continue
                links=[source(l,"DocumentReference") for l in r.get("supportingInformation",[])]
                docs=[d for d in links if d and d.get("status")=="current" and time(d["date"])<=cutoff]
                if not docs:continue
                if "medicationCodeableConcept" not in r or "medicationReference" in r:
                    unmapped=True
                    continue
                rx=codes(r["medicationCodeableConcept"],CATALOG["system"])
                products=CATALOG["products"]
                if len(rx)!=1 or next(iter(rx)) not in products:
                    unmapped=True
                    continue
                product=next(iter(rx)); definition=products[product]
                if definition["ingredient"]!=DRUG[fact]:continue
                found.append({"product":product,"ingredient":definition["ingredient"],"formulation":definition.get("formulation",definition["name"])})
                evidence.extend([ref(episode),ref(r),*(ref(d) for d in docs)])
            if found:return answer("IDENTITY_PRESENT","Source-linked administered product and ingredient; regimen, cycle, formulation allowance, line and timing criteria require separate evidence.",evidence,found)
            if unmapped:return answer("ENGINEERING_MAPPING","Unmapped or ambiguous product identity. Obtain the local product/concept dictionary or a normalized RxNorm product.")
            return answer("MISSING_DATA","No supported, source-linked completed administration for this episode. Absence of a match cannot exclude exposure.")
        d=CATALOG["diagnosis"]
        if codes(episode.get("verificationStatus",{}),d["verification_system"])!={"confirmed"}:
            return answer("MISSING_DATA","A confirmed episode-specific diagnosis is required.")
        sources=[];pathology=[]
        for evidence in episode.get("evidence",[]):
            for l in evidence.get("detail",[]):
                doc=source(l,"DocumentReference")
                if doc and doc.get("status")=="current" and time(doc["date"])<=cutoff:sources.append(ref(doc))
                report=source(l,"DiagnosticReport")
                if (report and report.get("status") in ("final","amended","corrected") and time(report["issued"])<=cutoff
                    and any("PAT" in codes(c,"http://terminology.hl7.org/CodeSystem/v2-0074") for c in report.get("category",[]))):
                    pathology.append(report);sources.append(ref(report))
        accepted={d["histology_code"][1],*(c[1] for c in d.get("additional_histology_codes",[]))}
        hist={v for e in episode.get("extension",[]) if e.get("url")==d["histology_extension"]
              for v in codes(e.get("valueCodeableConcept",{}),d["histology_code"][0])}
        snomed=codes(episode.get("code",{}),d["condition_code"][0])
        if hist-accepted or (d["condition_code"][1] in snomed and len(snomed)>1):
            return answer("ENGINEERING_MAPPING","Reconcile conflicting or unmapped tumor coding.",[ref(episode)])
        matching=[]
        for report in pathology:
            report_hist={v for c in report.get("conclusionCode",[]) for v in codes(c,d["histology_code"][0])}
            if report_hist-accepted:return answer("ENGINEERING_MAPPING","Resolve discrepant pathology histology.",[ref(episode),ref(report)])
            if report_hist&accepted:matching.append(ref(report))
        if fact=="histological_LMS_identity":
            # A pathology report must itself document the histology of the same condition.
            if not matching:return answer("MISSING_DATA","Obtain a verified pathology report with coded LMS histology linked to this cancer.")
            return answer("IDENTITY_PRESENT","Pathology documents LMS morphology; this does not establish grade, stage, extent or curability.",[ref(episode),*matching])
        if sources and (d["condition_code"][1] in snomed or hist&accepted):
            return answer("IDENTITY_PRESENT","Confirmed, source-linked episode-specific LMS identity.",[ref(episode),*sources])
        if not sources:return answer("MISSING_DATA","Obtain an attributable, versioned diagnosis or pathology source.")
        return answer("ENGINEERING_MAPPING","No exact supported LMS diagnosis or morphology coding.",[ref(episode)])
    except (ValueError,KeyError,TypeError,AttributeError) as e:
        return answer("MISSING_DATA",f"Verify the evidence input: {e}")


def fixture(leaf):
    t="2026-05-01T10:00:00Z"; meta={"versionId":"1","lastUpdated":t}; p="Patient/p"
    def r(kind,id,**fields):return dict(resourceType=kind,id=id,meta=meta,**fields)
    def cc(system,code):return {"coding":[dict(system=system,code=code)]}
    d=CATALOG["diagnosis"]
    path=r("DiagnosticReport","path",subject={"reference":p},status="final",issued=t,
           category=[cc("http://terminology.hl7.org/CodeSystem/v2-0074","PAT")],conclusionCode=[cc(*d["histology_code"])])
    doc=r("DocumentReference","med",subject={"reference":p},status="current",date=t)
    condition=r("Condition","tumor",subject={"reference":p},recordedDate=t,verificationStatus=cc(d["verification_system"],"confirmed"),
                code=cc(*d["condition_code"]),evidence=[{"detail":[{"reference":ref(path)}]}])
    med=r("MedicationAdministration","dose",subject={"reference":p},status="completed",effectiveDateTime=t,
          reasonReference=[{"reference":ref(condition)}],supportingInformation=[{"reference":ref(doc)}],
          medicationCodeableConcept=cc(CATALOG["system"],"1191138"))
    return {"resourceType":"Bundle","type":"collection","entry":[{"resource":v} for v in [r("Patient","p"),condition,path,doc,med]]}, {**leaf,"patient":p,"episode":"Condition/tumor","as_of":"2026-05-02T10:00:00Z"}


def run_checks():
    results=[]
    for leaf in LEAVES:
        fact=leaf["fact"]
        if fact in DRUG:
            product={"3639":"1191138","12574":"1719003","72962":"376888"}[DRUG[fact]]
            tests=[("source-linked-product",product,"IDENTITY_PRESENT"),("site-code-only","local","ENGINEERING_MAPPING"),
                   ("request-only","order","MISSING_DATA"),("not-completed","planned","MISSING_DATA"),
                   ("wrong-episode","episode","MISSING_DATA"),("different-patient","patient","MISSING_DATA"),
                   ("unversioned-source","unsourced","MISSING_DATA"),("unknown-product","unknown","ENGINEERING_MAPPING")]
            if DRUG[fact]=="3639": tests.append(("liposomal-identity-only","1790128","IDENTITY_PRESENT"))
        else:
            tests=[("confirmed-pathology","match","IDENTITY_PRESENT"),("unconfirmed","unconfirmed","MISSING_DATA"),
                   ("wrong-patient","patient","MISSING_DATA"),("unversioned-report","unsourced","MISSING_DATA"),
                   ("pathology-mismatch","mismatch","ENGINEERING_MAPPING")]
        for name,mode,expected in tests:
            b,ctx=fixture(leaf);v=[a["resource"] for a in b["entry"]];dx,path,med=v[1],v[2],v[4]
            if fact in DRUG:
                coding=med["medicationCodeableConcept"]["coding"][0];coding["code"]=product
                if mode in CATALOG["products"]:coding["code"]=mode
                elif mode=="local":coding.update(system="urn:unmapped:hospital",code="DOX")
                elif mode=="unknown":coding["code"]="999999999"
                elif mode=="order":med["resourceType"]="MedicationRequest"
                elif mode=="planned":med["status"]="on-hold"
                elif mode=="episode":med["reasonReference"]=[{"reference":"Condition/prior"}]
                elif mode=="patient":med["subject"]={"reference":"Patient/unrelated"}
                elif mode=="unsourced":med["supportingInformation"]=[]
            elif mode=="unconfirmed":dx["verificationStatus"]["coding"][0]["code"]="provisional"
            elif mode=="patient":dx["subject"]={"reference":"Patient/unrelated"}
            elif mode=="unsourced":dx["evidence"][0]["detail"]=[{"reference":"DiagnosticReport/path"}]
            elif mode=="mismatch":path["conclusionCode"][0]["coding"][0]["code"]="9999/3"
            output=resolve(b,ctx)
            results.append(dict(study=leaf["study"],criterion=leaf["criterion"],case=fact+"/"+name,expected=expected,actual=output["state"]))
    return results


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--bundle",type=Path);p.add_argument("--context",type=Path);p.add_argument("--self-test",action="store_true");a=p.parse_args()
    if a.self_test:
        checks=run_checks();print(json.dumps(checks,indent=2));raise SystemExit(0 if all(c["expected"]==c["actual"] for c in checks) else 1)
    if not a.bundle or not a.context:p.error("Provide --bundle and --context, or --self-test.")
    print(json.dumps(resolve(json.loads(a.bundle.read_text()),json.loads(a.context.read_text())),indent=2))
