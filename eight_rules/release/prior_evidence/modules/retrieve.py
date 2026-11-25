"""Plan patient-scoped R4 reads and retrieve candidate references from a normalized Collection Bundle.

No network access. A retrieved resource is a candidate for downstream binding, never an eligibility
result. --as-of describes when the source record was available. The returned clinical dates still
require the criterion-specific windows, anchors, and evidence adjudication.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlencode, urlsplit


# Resource: (R4 search parameter, paths to patient Reference). The search parameter is not
# necessarily the R4 field name. Never fall back to an unscoped type-wide read.
SCOPES = {
    name: ("subject", ("subject",)) for name in (
        "AdverseEvent", "CarePlan", "ClinicalImpression", "Communication", "Composition",
        "Condition", "DeviceUseStatement", "DiagnosticReport", "DocumentReference", "Encounter",
        "Flag", "Goal", "ImagingStudy", "List", "MedicationAdministration",
        "MedicationDispense", "MedicationRequest", "MedicationStatement", "Observation",
        "Procedure", "QuestionnaireResponse", "ServiceRequest", "Specimen",
    )
}
SCOPES.update({name: ("patient", ("patient",)) for name in (
    "AllergyIntolerance", "BodyStructure", "Consent", "EpisodeOfCare", "FamilyMemberHistory",
    "Immunization", "ImmunizationRecommendation", "MolecularSequence", "NutritionOrder",
    "RelatedPerson", "RiskAssessment",
)})
# Consult the patient-specific path in the R4 definitions even when search uses 'patient'.
SCOPES.update({
    "Patient": (None, ()), "RiskAssessment": ("subject", ("subject",)),
    "Task": ("patient", ("for",)), "ResearchSubject": ("individual", ("individual",)),
    "Appointment": ("patient", ("participant", "actor")),
    "CareTeam": ("subject", ("subject",)),
    "Media": ("subject", ("subject",)),
})
LINKED = {"Medication", "Device", "Provenance", "Binary"}
NON_PATIENT = {"ResearchStudy", "Location", "Organization", "Practitioner", "PractitionerRole",
               "ValueSet", "CodeSystem", "ConceptMap", "Questionnaire", "PlanDefinition", "ActivityDefinition"}
KNOWN = set(SCOPES) | LINKED | NON_PATIENT
TOKEN = re.compile(r"(?<![A-Za-z])("+"|".join(sorted(KNOWN,key=len,reverse=True))+r")(?![A-Za-z])")
ID = re.compile(r"[A-Za-z0-9.-]{1,64}\Z")
REF = re.compile(r"([A-Z][A-Za-z0-9]+)/([a-zA-Z0-9.-]{1,64})(?:/_history/([a-zA-Z0-9.-]{1,64}))?\Z")
UTC=timezone.utc


def strings(value):
    if isinstance(value,str):
        yield value
    elif isinstance(value,list):
        for item in value:
            yield from strings(item)
    elif isinstance(value,dict):
        for item in value.values():
            yield from strings(item)


def field(obj, path):
    values = [obj]
    for part in path:
        out = []
        for v in values:
            if isinstance(v,dict):
                child=v.get(part)
                if isinstance(child,list):
                    out.extend(child)
                elif child is not None:
                    out.append(child)
        values=out
    return values


def patient_id(value):
    raw = value.removeprefix("Patient/") if isinstance(value,str) else ""
    if raw in {".",".."} or not ID.fullmatch(raw):
        raise ValueError("Use one normalized Patient id.")
    return raw


def instant(value):
    if not isinstance(value,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",value):
        raise ValueError("An offset-qualified FHIR instant is required.")
    return datetime.fromisoformat(value.replace("Z","+00:00")).astimezone(UTC)


def find_row(study, criterion):
    matches=[row for row in study["criteria"] if row.get("id")==criterion]
    if len(matches)!=1:
        raise ValueError("Criterion ID is unavailable or ambiguous in selected study.")
    return matches[0]


def plan(study, criterion, patient):
    target="Patient/"+patient_id(patient)
    row=find_row(study,criterion)
    # Only the curated evidence descriptors and explicit normalized field selections are scanned.
    # Clinical source prose, labels, judgments, and rule expressions are never parsed as selectors.
    ds=list(strings(row.get("evidence",[])))
    external=[]
    for contract in row.get("predicate_contracts",[]):
        selector=contract.get("selector") or {}
        if contract.get("binding_mode")=="EXTERNAL_STUDY_STATE_ONLY" or selector.get("status")=="NOT_FROM_PATIENT_FHIR":
            external.append({"predicate_id":contract.get("predicate_id"), "requirement":contract.get("clinical_concept"),
                             "source_of_truth":selector.get("source_of_truth"),"required_fields":selector.get("required_fields",[])})
        else:
            ds.extend(strings([selector.get("fhir_json_root"),selector.get("json_path")]))
    declared={kind for descriptor in ds for kind in TOKEN.findall(descriptor)}
    queries=[]
    for kind in sorted(declared & set(SCOPES)):
        if kind=="Patient":
            url=target
        else:
            url=kind+"?"+urlencode({SCOPES[kind][0]:target})
        queries.append({"resource_type":kind,"request":"GET "+url})
    targeted=[]
    for item in row.get("terminology_candidates",[]):
        if "Observation" in declared and item.get("system")=="http://loinc.org" and item.get("code") and re.fullmatch(r"[0-9]+-[0-9]",item["code"]):
            # These specific concepts can supplement broad retrieval. They are not exhaustive.
            targeted.append({"code":item["code"],"request":"GET Observation?"+urlencode(
                {"subject":target,"code":item["system"]+"|"+item["code"]})})
    return {"mode":"candidate_retrieval_plan","study":study["study"],"version":study.get("version"),
            "criterion":criterion,"patient":target,"source_locator":row.get("locator"),
            "queries":queries,"additional_candidate_queries":targeted,"reference_only":sorted(declared & LINKED),
            "non_patient_resources":sorted(declared & NON_PATIENT),"external_state_contracts":external,
            "evidence_descriptors":row.get("evidence",[]),"open_requirements":row.get("remaining",[]),
            "untyped_descriptors":[s for s in strings(row.get("evidence",[])) if not TOKEN.search(s)],
            "limit":"Scope searches by patient. Use versioned source snapshots for historical screening. "
                    "Search coverage, enrollment dates, assay selection, joins, and site records require separate verification."}


class Snapshot:
    def __init__(self,bundle,at):
        if not isinstance(bundle,dict) or bundle.get("resourceType")!="Bundle" or bundle.get("type")!="collection":
            raise ValueError("Use a normalized R4 Bundle of type collection.")
        if not isinstance(bundle.get("entry",[]),list):
            raise ValueError("Invalid Bundle.entry.")
        self.at=at
        self.aliases={}
        full_urls={}
        self.versions=defaultdict(dict)
        for entry in bundle.get("entry",[]):
            res=entry.get("resource") if isinstance(entry,dict) else None
            if not isinstance(res,dict) or not isinstance(res.get("id"),str) or res["id"] in {".",".."} or not ID.fullmatch(res["id"]):
                raise ValueError("Each bundle entry must have a valid logical resource ID.")
            kind=res.get("resourceType","")
            if not isinstance(kind,str) or not re.fullmatch(r"[A-Z][A-Za-z0-9]*",kind):
                raise ValueError("Invalid FHIR resource type.")
            ref=kind+"/"+res["id"]
            url=entry.get("fullUrl")
            if url:
                if not isinstance(url,str):
                    raise ValueError("Invalid resource fullUrl.")
                parsed=urlsplit(url)
                if parsed.scheme in {"http","https"}:
                    if (not parsed.netloc or parsed.query or parsed.fragment
                            or not parsed.path.endswith("/"+ref)):
                        raise ValueError("Resource fullUrl disagrees with resource identity.")
                elif not re.fullmatch(r"urn:(?:uuid|oid):[a-zA-Z0-9.-]+",url):
                    raise ValueError("Use an absolute resource fullUrl or an explicit Bundle URN.")
                if (url in self.aliases and self.aliases[url]!=ref) or (ref in full_urls and full_urls[ref]!=url):
                    raise ValueError("Ambiguous resource fullUrl.")
                self.aliases[url]=ref
                full_urls[ref]=url
            meta=res.get("meta") or {}
            version=meta.get("versionId")
            # Fail closed: an undated or unversioned competing revision could supersede others.
            if not isinstance(version,str) or version in {".",".."} or not ID.fullmatch(version):
                raise ValueError("Each resource requires meta.versionId.")
            when=instant(meta.get("lastUpdated"))
            if version in self.versions[ref] and self.versions[ref][version]!=(when,res):
                raise ValueError("Conflicting copies of one resource version.")
            self.versions[ref][version]=(when,res)
        self.resources={}
        for ref,versions in self.versions.items():
            visible=[(t,v,r) for v,(t,r) in versions.items() if t<=at]
            if visible:
                latest=max(t for t,_,_ in visible)
                current=[r for t,_,r in visible if t==latest]
                if len(current)!=1:
                    raise ValueError("Ambiguous latest revision at the requested as-of time.")
                self.resources[ref]=current[0]

    def normalized_ref(self,reference):
        if not isinstance(reference,str):
            return None
        relative=self.aliases.get(reference,reference)
        m=REF.fullmatch(relative)
        if not m:
            return None
        kind,id,version=m.groups()
        # For explicit version links preserve the selected resource version, even if not latest.
        if version:
            when_res=self.versions.get(kind+"/"+id,{}).get(version)
            if not when_res or when_res[0]>self.at:
                return None
        return kind+"/"+id,version

    def resolve_current(self,ref):
        resolved=self.normalized_ref(ref)
        if not resolved:return None
        key,version=resolved
        res=self.resources.get(key)
        if not res or (version and res["meta"]["versionId"]!=version):
            return None
        return key,res


def versioned(key,res):
    return key+"/_history/"+res["meta"]["versionId"]


def same_patient(snap,res,target):
    if res["resourceType"]=="Patient":
        return res["resourceType"]+"/"+res["id"]==target
    path=SCOPES[res["resourceType"]][1]
    refs=[snap.normalized_ref(x.get("reference")) for x in field(res,path) if isinstance(x,dict)]
    patient_refs={ref[0] for ref in refs if ref and ref[0].startswith("Patient/")}
    if res["resourceType"]=="Appointment":
        # Multisubject appointments are never emitted as a single-patient evidence record.
        if any(ref is None for ref in refs):return False
    return patient_refs=={target}


def effective_dates(res):
    # Exclude plainly future observations/interventions; in-window clinical selection is downstream.
    timestamp_keys={
        "Observation":["effectiveDateTime","effectiveInstant","issued"],"DiagnosticReport":["effectiveDateTime","issued"],
        "Procedure":["performedDateTime"],"Immunization":["occurrenceDateTime"],
        "MedicationAdministration":["effectiveDateTime"],"Consent":["dateTime"],"QuestionnaireResponse":["authored"],
        "ImagingStudy":["started"],"DocumentReference":["date"],"AdverseEvent":["date","recordedDate"],
        "ClinicalImpression":["date","effectiveDateTime"],"MedicationStatement":["dateAsserted"],
        "MedicationRequest":["authoredOn"],"ServiceRequest":["authoredOn"],"Condition":["onsetDateTime","recordedDate"],
        "Specimen":["receivedTime"],"Provenance":["recorded"],"Encounter":[]}
    for k in timestamp_keys.get(res["resourceType"],[]):
        if k in res:yield res[k]
    for k in ("effectivePeriod","performedPeriod","onsetPeriod","period"):
        if isinstance(res.get(k),dict) and "start" in res[k]:
            yield res[k]["start"]
    if res["resourceType"]=="Specimen" and isinstance(res.get("collection"),dict):
        collection=res["collection"]
        if "collectedDateTime" in collection:yield collection["collectedDateTime"]


def available(res,at):
    for value in effective_dates(res):
        if isinstance(value,str) and re.fullmatch(r"\d{4}(?:-\d{2}(?:-\d{2})?)?",value):
            # At date precision, a same-day event could be after the cutoff. Require the entire
            # period to have elapsed; never manufacture clock times from partial source dates.
            import calendar
            try:
                year,month,day=(list(map(int,value.split("-")))+[0,0])[:3]
                month=month or 12
                end=datetime(year,month,day or calendar.monthrange(year,month)[1],23,59,59,999999,tzinfo=UTC)
            except (ValueError,OverflowError):return False
            if end>at:return False
        else:
            try:
                if instant(value)>at:return False
            except ValueError:return False
    if res.get("status")=="entered-in-error" or res.get("modifierExtension") or res.get("implicitRules"):
        return False
    return True


def retrieve(study, criterion, patient, bundle, as_of):
    at=instant(as_of)
    p=plan(study,criterion,patient)
    snap=Snapshot(bundle,at)
    target=p["patient"]
    if target not in snap.resources or not available(snap.resources[target],at):
        raise ValueError("The requested patient has no usable version as of the cutoff.")
    requested={q["resource_type"] for q in p["queries"]}
    accepted={}
    for key,res in snap.resources.items():
        kind=res["resourceType"]
        if kind in requested and same_patient(snap,res,target) and available(res,at):
            accepted[key]=res
    matches=[]
    for key,res in sorted(accepted.items()):
        refs=[]
        # Emit only existing links to source records that have their own valid patient scope.
        for name in ("derivedFrom","result","specimen","encounter","context","sourceReference","report"):
            for reference in field(res,(name,)):
                if not isinstance(reference,dict):continue
                node=snap.resolve_current(reference.get("reference"))
                if node and node[1]["resourceType"] in SCOPES and same_patient(snap,node[1],target) and available(node[1],at):
                    refs.append(versioned(*node))
        matches.append({"candidate":versioned(key,res),"last_updated":res["meta"]["lastUpdated"],
                        "source_links":sorted(set(refs))})
    supporting=set()
    if "Provenance" in p["reference_only"]:
        for key,res in snap.resources.items():
            if res["resourceType"]!="Provenance" or not available(res,at):continue
            targets=[snap.resolve_current(v.get("reference")) if isinstance(v,dict) else None for v in res.get("target",[])]
            if targets and all(t and t[0] in accepted for t in targets):
                supporting.add(versioned(key,res))
    for res in accepted.values():
        for name in ("medicationReference","device"):
            for item in field(res,(name,)):
                if not isinstance(item,dict):continue
                node=snap.resolve_current(item.get("reference"))
                if node and node[1]["resourceType"] in {"Medication","Device"} & set(p["reference_only"]):
                    linked=node[1]
                    if linked["resourceType"]=="Device" and linked.get("patient"):
                        owner=snap.normalized_ref(linked["patient"].get("reference"))
                        if not owner or owner[0]!=target:continue
                    if available(linked,at):supporting.add(versioned(*node))
    return {"mode":"patient_scoped_candidates","study":p["study"],"criterion":criterion,"patient":target,
            "as_of":as_of,"candidates":matches,"supporting_references":sorted(supporting),
            "non_patient_resources":p["non_patient_resources"],"external_state_contracts":p["external_state_contracts"],
            "meaning":"Candidates available for binding. Results do not establish a criterion decision or a complete record."}


def run_checks():
    """Synthetic transport tests; no trial eligibility predictions."""
    as_of="2026-01-01T18:00:00Z"
    study={"study":"SYNTHETIC","version":"1","criteria":[{"id":"R","locator":"fixture",
           "evidence":["Observation.code, Consent.patient, Encounter.subject, MedicationAdministration.subject, "
                       "ResearchStudy.site, Medication identifier, Provenance.target, ResearchSubject.individual."]}]}
    def r(kind,id,v="1",stamp="2026-01-01T10:00:00Z",**values):
        return {"resourceType":kind,"id":id,"meta":{"versionId":v,"lastUpdated":stamp},**values}
    a={"reference":"Patient/a"}
    b={"reference":"Patient/b"}
    doc=r("DocumentReference","good",subject=a)
    bad_doc=r("DocumentReference","other",subject=b)
    entries=[r("Patient","a"),r("Patient","b"),doc,bad_doc,
             r("Observation","allowed",subject=a,derivedFrom=[{"reference":"DocumentReference/good/_history/1"},
                                                            {"reference":"DocumentReference/other"}]),
             r("Observation","wrong",subject=b),r("Observation","noowner"),
             r("Observation","future",subject=a,effectiveDateTime="2026-02-01T01:00:00Z"),
             r("Observation","changed",subject=a),r("Observation","changed","2","2026-02-01T01:00:00Z",subject=b),
             r("Observation","subject-urn",subject={"reference":"urn:uuid:a"}),
             r("Observation","unresolved-absolute",subject={"reference":"https://unknown.example/Patient/a"}),
             r("Consent","c",patient=a),r("ResearchSubject","s",individual=a),r("Encounter","visit",subject=a),
             r("MedicationAdministration","med",subject=a,medicationReference={"reference":"Medication/drug"}),
             r("Medication","drug"),r("Medication","unlinked"),r("ResearchStudy","site"),
             r("Provenance","source",recorded="2026-01-01T10:00:00Z",target=[{"reference":"Observation/allowed/_history/1"}]),
             r("Provenance","unrelated",target=[{"reference":"Observation/allowed"},{"reference":"Observation/wrong"}])]
    bdl={"resourceType":"Bundle","type":"collection","entry":[{"resource":item,**({"fullUrl":"urn:uuid:a"} if item["resourceType"]=="Patient" and item["id"]=="a" else {})} for item in entries]}
    p=plan(study,"R","a")
    data=retrieve(study,"R","a",bdl,as_of)
    cand={x["candidate"]:x["source_links"] for x in data["candidates"]}
    req={q["request"] for q in p["queries"]}
    checks=[
        ("patient-safe search parameters",
         {"GET Consent?patient=Patient%2Fa","GET MedicationAdministration?subject=Patient%2Fa",
          "GET ResearchSubject?individual=Patient%2Fa","GET Encounter?subject=Patient%2Fa"}.issubset(req)),
        ("cross-patient and missing identity excluded",all(x not in cand for x in ("Observation/wrong/_history/1","Observation/noowner/_history/1"))),
        ("dated future clinical evidence excluded","Observation/future/_history/1" not in cand),
        ("future resource version not used","Observation/changed/_history/1" in cand and "Observation/changed/_history/2" not in cand),
        ("exact local Bundle UUID accepted","Observation/subject-urn/_history/1" in cand),
        ("foreign absolute subject not matched","Observation/unresolved-absolute/_history/1" not in cand),
        ("only linked same-patient source emitted",cand.get("Observation/allowed/_history/1")==["DocumentReference/good/_history/1"]),
        ("only scoped provenance and medication emitted",set(data["supporting_references"])=={"Medication/drug/_history/1","Provenance/source/_history/1"}),
        ("site study never retrieved as patient evidence",data["non_patient_resources"]==["ResearchStudy"] and all(not x.startswith("ResearchStudy/") for x in cand)),
    ]
    other_study={"study":"OTHER","version":"2","criteria":[{"id":"R","locator":"different source",
                 "evidence":["AllergyIntolerance.patient"]}]}
    other_plan=plan(other_study,"R","Patient/a")
    checks.append(("identical local criterion IDs use their own study descriptors",
                   other_plan["study"]=="OTHER" and other_plan["queries"]==[
                       {"resource_type":"AllergyIntolerance","request":"GET AllergyIntolerance?patient=Patient%2Fa"}]))
    checks.append(("patient retrieval does not include research operations or clinical judgments",
                   "eligibility" not in data and "decision" not in data))
    import copy
    for label, mutate in [
        ("spoofed relative fullUrl rejected",lambda bundle:bundle["entry"][1].update(fullUrl="Patient/a")),
        ("mismatched absolute fullUrl rejected",lambda bundle:bundle["entry"][1].update(fullUrl="https://site.example/fhir/Patient/a")),
        ("ambiguous versions rejected", lambda bundle:bundle["entry"].append({"resource":r("Patient","a","9")})),
        ("unversioned evidence rejected",lambda bundle:bundle["entry"][4]["resource"]["meta"].pop("versionId")),
        ("uncertain resource timestamp rejected",lambda bundle:bundle["entry"][4]["resource"]["meta"].update(lastUpdated="2026-01-01"))]:
        bad=copy.deepcopy(bdl);mutate(bad)
        try:retrieve(study,"R","a",bad,as_of)
        except ValueError:has_rejected=True
        else:has_rejected=False
        checks.append((label,has_rejected))
    return [{"criterion":"SHARED-FHIR-RETRIEVAL","case":label,"expected":True,"actual":value} for label,value in checks]


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    sub=cli.add_subparsers(dest="operation",required=True)
    for name in ("plan","retrieve"):
        cmd=sub.add_parser(name)
        cmd.add_argument("--study",type=Path,required=True,help="Path to study JSON with curated criteria")
        cmd.add_argument("--criterion",required=True)
        cmd.add_argument("--patient",required=True,help="FHIR Patient id (with optional Patient/ prefix)")
        if name=="retrieve":
            cmd.add_argument("--bundle",type=Path,required=True)
            cmd.add_argument("--as-of",required=True)
    sub.add_parser("check")
    args=cli.parse_args()
    try:
        if args.operation=="check":
            out=run_checks()
        else:
            study=json.loads(args.study.read_text())
            if args.operation=="plan":
                out=plan(study,args.criterion,args.patient)
            else:
                out=retrieve(study,args.criterion,args.patient,json.loads(args.bundle.read_text()),args.as_of)
        print(json.dumps(out,indent=2,ensure_ascii=False))
        return int(args.operation=="check" and any(t["actual"]!=t["expected"] for t in out))
    except (ValueError,KeyError,OSError,TypeError) as exc:
        cli.exit(2,f"Retrieval held: {exc}\n")


if __name__=="__main__":
    raise SystemExit(main())
