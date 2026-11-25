"""Replay each criterion against minimal, synthetic resource records to isolate FHIR retrieval scope.

These structural fixtures do not establish resource profile conformance or eligibility.
The expected patient paths below are independent of the planner's lookup table.
"""
from catalog import ROOT, read, STUDIES
from retrieve import plan, retrieve

NOW = "2026-01-10T17:00:00Z"
BEFORE = "2026-01-01T00:00:00Z"
AFTER = "2026-01-11T00:00:00Z"
PATIENT_FIELD = {
    "AllergyIntolerance", "BodyStructure", "Consent", "EpisodeOfCare", "FamilyMemberHistory",
    "Immunization", "ImmunizationRecommendation", "MolecularSequence", "NutritionOrder", "RelatedPerson",
}

def shape(kind, rid, owner, stamp=BEFORE, version="1"):
    ref={"reference":"Patient/"+owner}
    r={"resourceType":kind,"id":rid,"meta":{"lastUpdated":stamp,"versionId":version}}
    if kind=="Patient": return r
    if kind=="Appointment": r["participant"]=[{"actor":ref}]
    elif kind=="ResearchSubject": r["individual"]=ref
    elif kind=="Task": r["for"]=ref
    elif kind in PATIENT_FIELD: r["patient"]=ref
    else: r["subject"]=ref
    return r

def run_checks():
    cases=[]
    cache={}
    for s in STUDIES:
        study=read(ROOT/"studies"/(s+".json"))
        for c in study["criteria"]:
            criterion=c["id"]
            kinds=tuple(sorted(q["resource_type"] for q in plan(study,criterion,"alpha")["queries"]))
            if kinds not in cache:
                recs=[shape("Patient",label,label) for label in ("alpha","beta")]
                recs.append(shape("Patient","alpha","alpha",AFTER,"2"))
                expected={"Patient/alpha/_history/1"} if "Patient" in kinds else set()
                for kind in kinds:
                    if kind=="Patient": continue
                    recs.extend([shape(kind,"one","alpha"),shape(kind,"two","beta"),shape(kind,"three","alpha",AFTER)])
                    expected.add(kind+"/one/_history/1")
                cache[kinds]=({"resourceType":"Bundle","type":"collection","entry":[{"resource":r} for r in recs]},expected)
            bundle,expected=cache[kinds]
            result=retrieve(study,criterion,"alpha",bundle,NOW)
            got={item["candidate"] for item in result["candidates"]}
            cases.append({"study":s,"criterion":criterion,"case":"retrieve all declared patient resource types with subject and cutoff isolation",
                          "expected":sorted(expected),"actual":sorted(got)})
    return cases
