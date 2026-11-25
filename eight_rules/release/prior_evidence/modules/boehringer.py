"""1479-0032 v2, §3.3.3(7), p.51. Synthetic research implementation.

Run: python boehringer.py --self-test
Or:  python boehringer.py --bundle chart.json --context study-context.json
Context: {"study":"1479-0032","version":"2.0","patient":"Patient/demo",
"randomization":"2026-05-30T08:00:00-07:00","as_of":"2026-05-30T08:00:00-07:00",
"timezone":"America/Los_Angeles"}.
Input is an as-of, normalized FHIR R4 collection Bundle, one resource version
per logical ID. Only independently documented final assessments are supported.
Routine-care assessments in the screening window on pp. 8–9/99 may be used
when their exact version is included in the normalized context's
accepted_routine_evidence list. Otherwise the encounter must identify this
patient's study screening using the local fixture identifier below.
Do not use this module for a hospital feed without validating its crosswalk.
"""
import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

RULES = ["1479-0032-E07"]
LOINC = "http://loinc.org"
SCORE = "98152-2"  # https://loinc.org/98152-2
LOCAL = "urn:pocketmd:research:child-pugh"
CLASS = "documented-child-pugh-class"
STUDY_ID_SYSTEM = "urn:pocketmd:demo:screening-study"
# Grades and total score: https://www.cdisc.org/kb/qrs/child-pugh-classification
# Class uses a local normalized coded observation and value; no display-text match.
_ID = re.compile(r"^[A-Za-z0-9.\-]{1,64}$")


def instant(value):
    if not isinstance(value,str):
        raise ValueError("An offset-qualified timestamp is missing.")
    parsed = datetime.fromisoformat(value.replace("Z","+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("A full timestamp and UTC offset are required.")
    return parsed


def logical(r):
    if not isinstance(r,dict) or not isinstance(r.get("id"),str) or not _ID.fullmatch(r["id"]):
        raise ValueError("A normalized resource is missing its logical ID.")
    return f'{r["resourceType"]}/{r["id"]}'


def version(r):
    v = r["meta"]["versionId"]
    if not isinstance(v,str) or not _ID.fullmatch(v):
        raise ValueError("A version is required for auditable evidence.")
    return logical(r)+"/_history/"+v


def check_val(r, kind):
    fields = {k for k in r if k.startswith("value")}
    if "dataAbsentReason" in r:
        raise ValueError("Obtain the documented Child-Pugh result.")
    if kind=="class":
        if fields!={"valueCodeableConcept"}:
            raise ValueError("Verify the coded Child-Pugh class.")
        codes={c.get("code") for c in r["valueCodeableConcept"]["coding"] if c.get("system")==LOCAL}
        if len(codes)!=1 or not codes.issubset({"A","B","C"}):
            raise ValueError("Unknown or conflicting Child-Pugh class.")
        return codes.pop(), None
    if fields=={"valueInteger"}:
        n=r["valueInteger"]
    elif fields=={"valueQuantity"}:
        q=r["valueQuantity"]
        if q.get("system")!="http://unitsofmeasure.org" or q.get("code")!="{score}" or "comparator" in q:
            raise ValueError("A Child-Pugh total needs an exact score.")
        n=q["value"]
    else:
        raise ValueError("Verify a single documented total.")
    if type(n) not in (int,float) or not 5<=n<=15 or int(n)!=n:
        raise ValueError("Child-Pugh total must be an integer between 5 and 15.")
    return ("A" if n<=6 else "B" if n<=9 else "C"),int(n)


def screen(bundle, context):
    evidence=set()
    def result(state,reason):
        return dict(criterion=RULES[0],state=state,reason=reason,evidence=sorted(evidence))
    try:
        if context["study"]!="1479-0032" or context["version"]!="2.0":
            raise ValueError("Wrong study or protocol version.")
        patient=context["patient"]
        if not isinstance(patient,str) or not patient.startswith("Patient/") or not _ID.fullmatch(patient[8:]):
            raise ValueError("A normalized patient reference is required.")
        zone=ZoneInfo(context["timezone"])
        anchor=instant(context["randomization"])
        cutoff=min(anchor,instant(context["as_of"]))
        planned_day=anchor.astimezone(zone).date()
        if bundle.get("resourceType")!="Bundle" or bundle.get("type")!="collection":
            raise ValueError("Provide an as-of normalized FHIR collection Bundle.")
        resources={}
        for entry in bundle["entry"]:
            r=entry["resource"]
            if instant(r["meta"]["lastUpdated"])>cutoff:
                continue
            k=logical(r)
            if k in resources:
                raise ValueError("Provide one as-of version per logical resource.")
            resources[k]=r
        if patient not in resources:
            raise ValueError("The requested patient is not in the as-of snapshot.")
        evidence.add(version(resources[patient]))
        routine=context.get("accepted_routine_evidence", [])
        if not isinstance(routine,list) or any(not isinstance(ref,str) for ref in routine):
            raise ValueError("Provide versioned references for screening-approved routine results.")
        candidates=[]
        for r in resources.values():
            if r["resourceType"]!="Observation" or r.get("subject",{}).get("reference")!=patient:
                continue
            if r.get("status") in {"cancelled","entered-in-error"}:
                continue
            codings={(c.get("system"),c.get("code")) for c in r.get("code",{}).get("coding",[])}
            matches={k for k,v in [("score",(LOINC,SCORE)),("class",(LOCAL,CLASS))] if v in codings}
            if not matches:
                continue
            encounter_ref=r.get("encounter",{}).get("reference","")
            visit=resources.get(encounter_ref.split("/_history/")[0])
            verified_visit=(visit and visit["resourceType"]=="Encounter"
                            and encounter_ref in (logical(visit),version(visit))
                            and visit.get("subject",{}).get("reference")==patient
                            and visit.get("status") in ("in-progress","finished")
                            and [i.get("value") for i in visit.get("identifier",[])
                                 if i.get("system")==STUDY_ID_SYSTEM]==[context["study"]])
            if not verified_visit and version(r) not in routine:
                continue
            stamp=instant(r["effectiveDateTime"])
            delta=(stamp.astimezone(zone).date()-planned_day).days
            if not -28<=delta<=-1 or stamp>cutoff:
                continue
            if r.get("issued") and instant(r["issued"])>cutoff:
                continue
            candidates.append((stamp,r,codings,matches,version(visit) if verified_visit else None))
        if not candidates:
            return result("MISSING_DATA","Obtain the latest documented Child-Pugh class or score during screening.")
        latest=max(item[0] for item in candidates)
        classes,scores=set(),set()
        for stamp,r,codings,matches,visit in candidates:
            if stamp!=latest: continue
            evidence.add(version(r))
            if visit:
                evidence.add(visit)
            if (len(matches)!=1 or r.get("modifierExtension") or r.get("implicitRules")
                    or r.get("status") not in {"final","amended","corrected"}
                    or {k for k in r if k.startswith("effective")}!={"effectiveDateTime"}
                    or instant(r["issued"])<stamp):
                raise ValueError("Latest assessment needs a single verified measure, time and final result.")
            kind=next(iter(matches))
            if kind=="score" and any(system==LOINC and code!=SCORE for system,code in codings):
                raise ValueError("The observation contains conflicting LOINC codes.")
            if kind=="class" and any(system==LOCAL and code!=CLASS for system,code in codings):
                raise ValueError("The observation contains conflicting normalized measure codes.")
            docs=r.get("derivedFrom",[])
            if not docs:
                raise ValueError("Obtain the versioned source for this assessment.")
            for link in docs:
                target=link["reference"]
                doc=resources.get(target.split("/_history/")[0])
                if (not doc or doc["resourceType"]!="DocumentReference" or target!=version(doc)
                    or doc.get("subject",{}).get("reference")!=patient or doc.get("status")!="current"
                    or doc.get("modifierExtension") or doc.get("implicitRules")
                    or (doc.get("date") and instant(doc["date"])>cutoff)):
                    raise ValueError("Verify the assessment's source, version and patient.")
                evidence.add(target)
            cls,score=check_val(r,kind)
            classes.add(cls)
            if score is not None: scores.add(score)
        if len(classes)!=1 or len(scores)>1:
            raise ValueError("Conflicting assessments at the latest timestamp require reconciliation.")
        excluded=next(iter(classes))=="C"
        return result("NOT_MET" if excluded else "MET",
                      "The documented assessment triggers the severe hepatic impairment exclusion."
                      if excluded else "The documented Child-Pugh result clears this exclusion.")
    except (KeyError,TypeError,ValueError,AttributeError,ZoneInfoNotFoundError) as ex:
        return result("MISSING_DATA",f"Verify study scope, chronology or evidence: {ex}")


def _fixture(observations):
    patient="Patient/demo"
    context=dict(study="1479-0032",version="2.0",patient=patient,randomization="2026-05-30T12:00:00Z",
                 as_of="2026-05-30T12:00:00Z",timezone="UTC")
    m={"versionId":"1","lastUpdated":"2026-05-01T12:00:00Z"}
    items=[dict(resourceType="Patient",id="demo",meta=m),
           dict(resourceType="Encounter",id="study-screen",status="finished",meta=m,
                subject={"reference":patient},identifier=[{"system":STUDY_ID_SYSTEM,"value":"1479-0032"}])]
    for i,(kind,v,when,overrides) in enumerate(observations):
        date_time=when+"T10:00:00Z"
        metadata={"versionId":"1","lastUpdated":date_time}
        doc=dict(resourceType="DocumentReference",id=f"source{i}",meta=metadata,status="current",
                 subject={"reference":patient},date=date_time,content=[{"attachment":{"contentType":"text/plain","title":"Synthetic Child-Pugh test"}}])
        r=dict(resourceType="Observation",id=f"obs{i}",meta=metadata,status="final",subject={"reference":patient},
               encounter={"reference":"Encounter/study-screen"},effectiveDateTime=date_time,issued=date_time,derivedFrom=[{"reference":version(doc)}])
        if kind=="class":
            r.update(code={"coding":[{"system":LOCAL,"code":CLASS}]},
                     valueCodeableConcept={"coding":[{"system":LOCAL,"code":v}]})
        else:
            r.update(code={"coding":[{"system":LOINC,"code":SCORE}]},valueInteger=v)
        r.update(overrides)
        items.extend([r,doc])
    return {"resourceType":"Bundle","type":"collection","entry":[{"resource":r} for r in items]},context


def run_checks():
    day="2026-05-20"
    def obs(kind,value,stamp=day,**changes): return kind,value,stamp,changes
    cases = [
        ("score-5","MET",[obs("score",5)]),("score-9","MET",[obs("score",9)]),
        ("score-10","NOT_MET",[obs("score",10)]),("score-15","NOT_MET",[obs("score",15)]),
        ("class-A","MET",[obs("class","A")]),("class-B","MET",[obs("class","B")]),
        ("class-C","NOT_MET",[obs("class","C")]),("missing","MISSING_DATA",[]),
        ("conflict-class-score","MISSING_DATA",[obs("class","B"),obs("score",10)]),
        ("agree-class-score","NOT_MET",[obs("class","C"),obs("score",10)]),
        ("conflict-tied-scores","MISSING_DATA",[obs("score",10),obs("score",15)]),
        ("latest","NOT_MET",[obs("class","B","2026-05-10"),obs("score",10)]),
        ("out-of-range","MISSING_DATA",[obs("score",16)]),("low-out-of-range","MISSING_DATA",[obs("score",4)]),
        ("fractional","MISSING_DATA",[obs("score",9.1)]),("unknown-class","MISSING_DATA",[obs("class","unknown")]),
        ("wrong-patient","MISSING_DATA",[obs("class","C",subject={"reference":"Patient/other"})]),
        ("wrong-source-version","MISSING_DATA",[obs("score",10,derivedFrom=[{"reference":"DocumentReference/source0/_history/5"}])]),
        ("day-minus-28","MET",[obs("score",8,"2026-05-02")]),("day-minus-29","MISSING_DATA",[obs("score",8,"2026-05-01")]),
        ("day-minus-1","MET",[obs("score",8,"2026-05-29")]),("day-zero","MISSING_DATA",[obs("score",10,"2026-05-30")]),
        ("requires-final","MISSING_DATA",[obs("score",10,status="preliminary")]),
        ("late-release","MISSING_DATA",[obs("score",10,issued="2026-06-01T09:00:00Z")]),
        ("other-measure","MISSING_DATA",[obs("score",10,code={"coding":[{"system":LOINC,"code":"98153-0"}]})]),
    ]
    results=[]
    for case,expect,data in cases:
        actual=screen(*_fixture(data))
        if actual['state'] in ('MET','NOT_MET'):
            assert any(r.startswith('Observation/') for r in actual['evidence'])
            assert any(r.startswith('DocumentReference/') for r in actual['evidence'])
        results.append(dict(criterion=RULES[0],case=case,expected=expect,actual=actual['state']))
    bundle,ctxt=_fixture([obs("score",10)])
    for name,cfg,expected in [('other-study',dict(study='other'),'MISSING_DATA'),
                              ('wrong-version',dict(version='1.0'),'MISSING_DATA'),
                              ('future-evidence-as-of',dict(as_of='2026-05-19T11:00:00Z'),'MISSING_DATA')]:
        results.append(dict(criterion=RULES[0],case=name,expected=expected,actual=screen(bundle,{**ctxt,**cfg})['state']))
    bundle,ctxt=_fixture([obs("class","B",encounter={"reference":"Encounter/unrelated"})])
    outside=screen(bundle,ctxt)
    results.append(dict(criterion=RULES[0],case="outside-study-no-routine-approval",expected="MISSING_DATA",actual=outside["state"]))
    approved=screen(bundle,{**ctxt,"accepted_routine_evidence":["Observation/obs0/_history/1"]})
    results.append(dict(criterion=RULES[0],case="in-window-approved-routine-result",expected="MET",actual=approved["state"]))
    return results


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--bundle",type=Path)
    parser.add_argument("--context",type=Path)
    args=parser.parse_args()
    if args.self_test:
        checks=run_checks()
        print(json.dumps(checks,indent=2))
        raise SystemExit(0 if all(c["expected"]==c["actual"] for c in checks) else 1)
    if not args.bundle or not args.context:
        parser.error("Provide --bundle and --context, or --self-test.")
    print(json.dumps(screen(json.loads(args.bundle.read_text()),json.loads(args.context.read_text())),indent=2))
