"""Evaluate the registered study age window at the documented patient presentation."""
import argparse
from copy import deepcopy
from xml.etree import ElementTree as ET
import base64
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
sys.path.insert(0, str(BENCH / "round11"))
from catalog import fact, verify, contract
from native import NativeChart

DEFAULT_CATALOG = BENCH / "round11/compiled.json"
MANIFEST_SHA256 = "2084977c389f84301d2aa40ed45aff401f2ec7af00704f24c80e1fc39f42a0da"
ORIGINALS = HERE / "registry/benchmark_2015"
SCOPE_REVIEWS_FILE = HERE / "registry/age_scope_reviews.json"
SCOPE_REVIEWS_SHA256 = "d47f5c52fa84ef3be05ae7b68dee81e3bdb3f79e28a707d3aae44733da1fae66"

AGE = fact("age_years", "number", "a")
AGE_UNIT = r"(?P<unit>year[ -]old|yo|month[ -]old|day[ -]old)"
UCUM = {"year":"a", "yo":"a", "month":"mo", "day":"d"}
SEX_OR_PERSON = r"(?:man|woman|male|female|girl|boy|child|patient|infant)"
DESCRIPTORS = r"(?:(?:white|black|caucasian|african[ -]american|obese|generally healthy|nonsmoker)\s+)*"

PATIENT_AGE = re.compile(
    r"^(?:\d+\.\s*)?(?:(?:the patient is |the patient, )?(?:a |an )?)"
    r"(?P<age>\d{1,3})(?:[ -]?" + AGE_UNIT + r")\s+" + DESCRIPTORS + SEX_OR_PERSON + r"\b", re.I)
RELATIVE = re.compile(r"\b(?:mother|father|parents?|sons?|daughters?|sisters?|brothers?|wife|husband|partner|relative|caregiver|siblings?)\b", re.I)
PRESENTATION = re.compile(r"\b(?:presents?|presented|arrives?|complains?|visits?|sees|is seen|"
                          r"is brought|was brought|is admitted|is evaluated|was recently in|fell|comes|"
                          r"is found|undergoes|describes|is hospitalized|was hospitalized|has)\b", re.I)


def read_json(path):
    return json.loads(Path(path).read_bytes())


def fingerprint(raw):
    return hashlib.sha256(raw).hexdigest()


def extract_index_age(line):
    """Require the opening presentation of the index person, with an explicit predicate."""
    match = PATIENT_AGE.match(line.strip())
    if not match:
        return None
    rest = line.strip()[match.end():]
    if re.search(r"\b(?:may|might|would|if|suppose|hypothetical|previously)\b", rest, re.I):
        return None
    verb = PRESENTATION.search(re.split(r"[.!?;]", rest, maxsplit=1)[0])
    if not verb or RELATIVE.search(rest[:verb.start()]) or re.search(r"[’']s\b", rest[:verb.start()]):
        return None
    if re.search(r"\b(?:accompan(?:ies|ying)|brought in|brings|reports that|says that|whose)\b", rest[:verb.start()], re.I):
        return None
    # Accept a relative only when the index patient was explicitly brought in by them.
    # Otherwise the described adult could be accompanying the patient.
    family_in_presentation = RELATIVE.search(rest[verb.start():]) or re.search(
        r"\b(?:his|her|their)\s+(?:(?:\d+[ -](?:year|month|day)[ -]old|sick)\s+)*child\b",rest[verb.start():],re.I)
    brought_by_family = re.match(r"(?:is|was) brought\b[^.!?;]*?\bby (?:his|her|their)\b",rest[verb.start():],re.I)
    if family_in_presentation and not brought_by_family:
        return None
    unit = re.match(r"[a-z]+", match["unit"].lower())[0]
    return int(match["age"]), UCUM[unit]


def verified_age(resources, subject, study, pack, expected_hash=None):
    if not re.fullmatch(r"Patient/[A-Za-z0-9.\-]{1,64}", subject or ""):
        return None, "INDIVIDUAL_PATIENT_REQUIRED"
    try:
        # Reuse the same coded FHIR selector, provenance check and typed reader for each UCUM unit.
        contracts = dict(pack["contracts"])
        for unit, label in (("mo", "age_months"), ("d", "age_days")):
            spec = fact(label, "number", unit)
            entry = deepcopy(contracts[contract(AGE)])
            entry["spec"] = spec
            for selector in entry["native"]:
                selector["unit"] = unit
            contracts[contract(spec)] = entry
        chart = NativeChart(resources, subject, contracts, study)
        if expected_hash is not None and chart.hash != expected_hash:
            return None, "PATIENT_SOURCE_HASH_MISMATCH"
        readings = []
        for unit, spec in (("a", AGE), ("mo", fact("age_months", "number", "mo")), ("d", fact("age_days", "number", "d"))):
            value, issue, refs, _ = chart.read(spec)
            if issue and refs:
                return None, "CONFLICTING_OR_INCOMPLETE_AGE"
            if not issue and refs:
                readings.append((unit, value, refs, contract(spec)))
        if len(readings) != 1:
            return None, "VERIFIED_PRESENTATION_AGE_UNAVAILABLE"
        unit, value, refs, contract_id = readings[0]
        if type(value) not in (int, float) or value != int(value):
            return None, "VERIFIED_PRESENTATION_AGE_UNAVAILABLE"
        note = next(r for r in resources if chart.source == r["resourceType"] + "/" + r["id"])
        lines = base64.b64decode(note["content"][0]["attachment"]["data"]).decode().splitlines()
        if not lines or extract_index_age(lines[0]) != (value, unit) or any(chart.refs.get(r) != [0] for r in refs):
            return None, "INDEX_PATIENT_PRESENTATION_AGE_UNVERIFIED"
    except (ValueError, KeyError, TypeError, UnicodeError, StopIteration, IndexError):
        return None, "INVALID_PATIENT_SOURCE"
    return {"value": int(value), "unit": unit, "completed_years": int(value) if unit == "a" else None,
            "contract": contract_id, "selectors": contracts[contract_id]["native"],
            "source": chart.source, "source_sha256": chart.hash,
            "line_index": 0, "excerpt": lines[0], "resources": refs, "anchor": "documented presentation"}, None


def original_registry(study, entries):
    """Bind trusted, version-aligned XML to the same criterion texts used by the catalog."""
    if not re.fullmatch(r"NCT\d{8}", study) or not entries:
        return None, "INVALID_STUDY_ID"
    try:
        raw_manifest = (ORIGINALS / "manifest.json").read_bytes()
        if fingerprint(raw_manifest) != MANIFEST_SHA256:
            return None, "ARCHIVE_MANIFEST_HASH_MISMATCH"
        manifest = json.loads(raw_manifest)
        source = manifest["studies"][study]
        dataset = manifest["dataset"]
        if source["path"] != "xml/" + study + ".xml":
            return None, "REGISTRY_IDENTITY_MISMATCH"
        raw = (ORIGINALS / source["path"]).read_bytes()
        digest = fingerprint(raw)
        if source["sha256"] != digest:
            return None, "REGISTRY_HASH_MISMATCH"
        root = ET.fromstring(raw)
        if root.findtext("id_info/nct_id") != study:
            return None, "REGISTRY_IDENTITY_MISMATCH"
        if source.get("benchmark_version_verified") is not True:
            return None, "BENCHMARK_REGISTRATION_VERSION_UNVERIFIED"
        joins = {str(r["case"]): r for r in source["criterion_joins"]}
        if set(joins) != set(entries) or any(
            joins[k]["frozen_criterion_sha256"] != fingerprint(v["source"]["criterion_text"].encode()) or
            joins[k]["criterion_type"] != v["source"]["criterion_type"] for k, v in entries.items()
        ):
            return None, "FROZEN_CRITERION_SOURCE_MISMATCH"
        if not any(j["status"] == "exact_lexical" for j in joins.values()):
            return None, "FROZEN_CRITERION_TEXT_NOT_ALIGNED"
        raw_bounds = {field:root.findtext("eligibility/" + xml_field)
                      for field, xml_field in (("minimumAge", "minimum_age"),("maximumAge", "maximum_age"))}
        if root.find("eligibility") is None or any(v is None for v in raw_bounds.values()):
            return None, "REGISTRY_SOURCE_UNAVAILABLE"
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError):
        return None, "REGISTRY_SOURCE_UNAVAILABLE"
    return {"url": "https://clinicaltrials.gov/study/" + study, "sha256": digest,
            "original_xml": source["path"], "archive_member": source["archive_member"],
            "archive_sha256": dataset["archive_sha256"], "archive_url": dataset["file_url"],
            "snapshot_date": dataset["snapshot_date"], "last_update": source["lastchanged_date"],
            "locator": "clinical_study/eligibility/{minimum_age,maximum_age}", "raw_bounds": raw_bounds,
            "bounds": {k:v for k,v in raw_bounds.items() if v != "N/A"},
            "catalog_criterion_ids": sorted(entries, key=int), "benchmark_version_verified":True}, None


def reviewed_anchor(study, source):
    """Look up the versioned result of reviewing population, arms and enrollment timing."""
    try:
        raw = SCOPE_REVIEWS_FILE.read_bytes()
        if fingerprint(raw) != SCOPE_REVIEWS_SHA256:
            return None
        review = json.loads(raw)["reviews"][study]
        xml = (ORIGINALS / source["original_xml"]).read_bytes()
        if review["source_sha256"] != source["sha256"] or fingerprint(xml) != source["sha256"]:
            return None
        root = ET.fromstring(xml)
        text = " ".join((root.findtext(review["locator"]) or "").split())
        if not review["excerpt"] or review["excerpt"] not in text:
            return None
        return review
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError):
        return None


def age_extent(value, unit):
    # Calendar years and months compare exactly in calendar months. For day-based
    # cross-unit comparisons, outward bounds enclose all possible birthdays.
    if unit == "a":
        return value * 12, (value + 1) * 12, value * 365, (value + 1) * 366
    if unit == "mo":
        return value, value + 1, value * 28, (value + 1) * 31
    return None, None, value, value + 1


def compare_bound(value, unit, bound, bound_unit):
    if unit == "d" and bound_unit == "d":
        return (value > bound) - (value < bound)
    months_min, months_end, days_min, days_end = age_extent(value, unit)
    lo, _, dlo, _ = age_extent(bound, bound_unit)
    if months_min is not None and lo is not None:
        # For an inclusive upper age reported in completed units, include the
        # entire upper unit before declaring a definite excess.
        upper_end = age_extent(bound + 1, bound_unit)[0]
        return -1 if months_end <= lo else 1 if months_min >= upper_end else 0
    max_days = age_extent(bound, bound_unit)[3]
    return -1 if days_end <= dlo else 1 if days_min >= max_days else 0


def age_window(age, bounds, unit="a"):
    if not bounds or type(age) != int or age < 0 or unit not in {"a", "mo", "d"}:
        return "UNRATED", "AGE_BOUND_ABSENT_OR_UNSUPPORTED"
    parsed = {}
    for field, raw in bounds.items():
        match = re.fullmatch(r"(\d+) (Year|Month|Day)s?", raw or "", flags=re.IGNORECASE) if isinstance(raw, str) else None
        if field not in {"minimumAge", "maximumAge"} or not match:
            return "UNRATED", "AGE_BOUND_ABSENT_OR_UNSUPPORTED"
        parsed[field] = (int(match[1]), UCUM[match[2].lower()])
    low, high = parsed.get("minimumAge"), parsed.get("maximumAge")
    if low and high:
        if low[1] == high[1]:
            ordered = low[0] <= high[0]
        elif "d" not in {low[1], high[1]}:
            ordered = age_extent(*low)[0] <= age_extent(*high)[0]
        else:
            # To accept mixed-unit source bounds, prove even the longest
            # minimum calendar interval ends before the earliest maximum.
            factor = {"a":366,"mo":31,"d":1}[low[1]]
            ordered = low[0] * factor <= age_extent(*high)[2]
        if not ordered:
            return "UNRATED", "INVALID_REGISTRY_AGE_WINDOW"
    if low and compare_bound(age, unit, *low) < 0:
        return "EXCLUDED_BY_AGE_AT_PRESENTATION", "BELOW_MINIMUM"
    if high and compare_bound(age, unit, *high) > 0:
        return "EXCLUDED_BY_AGE_AT_PRESENTATION", "ABOVE_MAXIMUM"
    return "NO_DEFINITE_AGE_EXCLUSION", "NO_PROVEN_AGE_VIOLATION"


def assess(resources, subject, study, pack, *, expected_hash=None):
    entries = {k:v for k,v in pack["rules"].items() if v["source"]["trial_id"] == study}
    source, reason = original_registry(study, entries)
    base = {"scope": "study_age_at_presentation", "subject": subject, "study": study,
            "catalog_sha256": pack["sha256"], "criterion_ids_for_study": sorted(entries, key=int),
            "registration": source, "patient_age": None}
    if source is None:
        return dict(base, state="UNRATED", reason=reason)
    age, reason = verified_age(resources, subject, study, pack, expected_hash)
    base["patient_age"] = age
    if age is None:
        return dict(base, state="UNRATED", reason=reason)
    state, reason = age_window(age["value"], source["bounds"], age["unit"])
    if state == "EXCLUDED_BY_AGE_AT_PRESENTATION":
        review = reviewed_anchor(study, source)
        if not review:
            return dict(base, state="UNRATED", reason="STUDY_AGE_SCOPE_REVIEW_REQUIRED")
        base["scope_review"] = review
        if review["anchor"] != "ENROLLMENT":
            return dict(base, state="UNRATED", reason="HISTORICAL_ENROLLMENT_AGE_REQUIRED")
    return dict(base, state=state, reason=reason)


def run():
    pack = verify(read_json(DEFAULT_CATALOG))
    assignments = read_json(BENCH / "round9/assignments.json")
    bundles = BENCH / "round12/export"
    subjects = {r["case"]:r["subject"] for r in read_json(bundles / "cases.json")}
    hashes = read_json(BENCH / "round9/note_hashes.json")
    groups = defaultdict(list)
    for r in assignments:
        cid, study = str(r["annotation_id"]), r["study"]
        if pack["rules"][cid]["source"]["trial_id"] != study:
            raise ValueError("The assigned criterion and catalog study disagree.")
        groups[(r["patient"], study)].append(r["annotation_id"])
    if {str(i) for group in groups.values() for i in group} != set(pack["rules"]):
        raise ValueError("Assignment ledger and catalog do not cover the same criteria.")
    receipts = []
    for (patient, study), ids in sorted(groups.items()):
        resources = [e["resource"] for e in read_json(bundles / "bundles" / (patient + ".json"))["entry"]]
        receipt = assess(resources, subjects[patient], study, pack, expected_hash=hashes[patient])
        receipt["assigned_criterion_ids"] = sorted(ids)
        receipts.append(receipt)
    excluded = [r for r in receipts if r["state"] == "EXCLUDED_BY_AGE_AT_PRESENTATION"]
    return {"scope": "Study age prescreen at documented presentation only",
            "assignments": len(assignments), "patient_study_pairs": len(groups),
            "pair_counts": dict(sorted(Counter(r["state"] for r in receipts).items())),
            "reason_counts": dict(sorted(Counter(r["reason"] for r in receipts).items())),
            "assignments_in_excluded_pairs": sorted(i for r in excluded for i in r["assigned_criterion_ids"]),
            "receipts": receipts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--subject")
    parser.add_argument("--study")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if any((args.subject, args.study, args.bundle)):
        if not all((args.subject, args.study, args.bundle)):
            parser.error("Single-patient screening requires --bundle, --subject and --study.")
        res = assess([e["resource"] for e in read_json(args.bundle)["entry"]], args.subject, args.study,
                     verify(read_json(DEFAULT_CATALOG)))
    else:
        res = run()
    if args.out:
        args.out.parent.mkdir(exist_ok=True, parents=True)
        args.out.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
        print(json.dumps({k:v for k,v in res.items() if k != "receipts"}, indent=2))
    else:
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
