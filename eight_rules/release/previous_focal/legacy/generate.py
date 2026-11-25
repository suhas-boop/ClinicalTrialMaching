"""Recompute browser traces and two synthetic FHIR evidence packets."""
import json
import sys
from pathlib import Path

from bridge import MICHIGAN, ROOT, SOTIO, _execute, michigan_demo, run_sotio

PINNED = ROOT / "pinned"
sys.path.insert(0, str(PINNED))
import assertions
import check_agreement
import check_prescreen
from screen import CATALOG

T = "2026-11-19T10:05:00Z"


def record(bundle, rt, id, **fields):
    resource = {"resourceType": rt, "id": id, "meta": {"versionId": "1", "lastUpdated": T}, **fields}
    bundle["entry"].append({"resource": resource})
    return resource


def link(target):
    return {"reference": target}


def concept(system, code):
    return {"coding": [{"system": system, "code": code}]}


def quantity(value, unit):
    return {"valueQuantity": {"value": value, "code": unit, "system": "http://unitsofmeasure.org"}}


def demo_packet(archive=False):
    bundle = check_prescreen.archive("safe-and-accessible") if archive else check_prescreen.fixture()
    visit = check_prescreen.resource(bundle, "screen")
    signed = assertions.example(SOTIO, "106S01-E13")
    for entry in signed["bundle"]["entry"]:
        resource = entry["resource"]
        if resource["resourceType"] == "Encounter":
            visit["identifier"].extend(resource["identifier"])
        elif resource["resourceType"] != "Patient":
            bundle["entry"].append(entry)
    agreement = check_agreement.resource(check_agreement.adult(), "agreement")
    bundle["entry"].append({"resource": agreement})
    record(bundle, "PractitionerRole", "study-investigator", active=True,
           code=[concept("urn:pocketmd:demo:study-roles", "investigator")],
           identifier=[{"system": "urn:pocketmd:demo:role-study", "value": SOTIO}],
           period={"start": "2026-01-01T00:00:00Z"})
    record(bundle, "Specimen", "serum", subject=link("Patient/demo"), status="available",
           type=concept("http://terminology.hl7.org/CodeSystem/v2-0487","SER"))
    for key, value in [
        ("ecog", {"valueInteger":1}), ("appropriate_candidate", {"valueBoolean": True}),
        ("estimated_survival", quantity(3,"mo")), ("qtcf",quantity(465,"ms")),
        ("anc",quantity(1.5,"10*9/L")), ("platelets",quantity(100,"10*9/L")),
        ("hemoglobin",quantity(9,"g/dL")), ("albumin",quantity(3,"g/dL")),
        ("severe_preexisting",{"valueBoolean":False}), ("substance_abuse",{"valueBoolean":False}),
        ("interstitial_pneumonitis_history",{"valueBoolean":False}), ("pulmonary_fibrosis_history",{"valueBoolean":False}),
        ("major_ventricular_arrhythmia_history",{"valueBoolean":False}),
        ("congenital_longqt",{"valueBoolean":False}), ("family_congenital_longqt",{"valueBoolean":False}),
        ("rbc_review", {"valueDateTime":"2026-11-17T09:00:00Z"})]:
        spec = CATALOG[key]
        slug = key.replace("_","-")
        role = [link("PractitionerRole/study-investigator/_history/1")] if spec.get("required_role") else []
        record(bundle, "DocumentReference", "note-"+slug, subject=link("Patient/demo"), status="current", date=T, author=role)
        obs = record(bundle, "Observation", slug, subject=link("Patient/demo"), encounter=link("Encounter/screen"),
               code=concept(spec["system"],spec["code"]), issued=T, effectiveDateTime=T, status="final",
               derivedFrom=[link("DocumentReference/note-"+slug+"/_history/1")], performer=role, **value)
        if key == "albumin":
            obs["specimen"] = link("Specimen/serum/_history/1")
    return {"bundle":bundle, "as_of":check_prescreen.CUTOFF, "timezone_name":"UTC", "patient":"Patient/demo",
            "encounter":"Encounter/screen", "onboarding":json.loads((PINNED / "demo-sotio-onboarding.json").read_text()),
            "trusted_signers":signed["context"]["trusted_signers"]}


def write(name, data, *, pretty=False):
    (ROOT/name).write_text(json.dumps(data, indent=2 if pretty else None, separators=None if pretty else (",",":"),
                                     ensure_ascii=False, allow_nan=False) + "\n")


def generate():
    expected = json.loads((PINNED/"michigan_expected.json").read_text())
    michigan = {k:michigan_demo(k) for k in expected}
    write("michigan_demo.json", _execute("michigan-packet", {"label":"all-met"}), pretty=True)
    sotio = {}
    for name, archival in (("fresh-biopsy",False),("archival-when-fresh-feasible",True)):
        packet = demo_packet(archival)
        write("sotio_"+("archive" if archival else "demo")+".json", packet, pretty=True)
        sotio[name] = run_sotio(**packet)
    write("legacy_replays.json", {MICHIGAN:michigan, SOTIO:sotio})
    return {MICHIGAN:len(michigan), SOTIO:len(sotio)}


if __name__=="__main__":
    print(json.dumps(generate(), indent=2))
