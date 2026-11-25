"""Versioned Michigan research evidence contracts and bridge to its sealed query executable."""
import json
import re
import subprocess
import sys
import tempfile
from copy import deepcopy
from datetime import date, datetime, time, timezone
from functools import lru_cache
from pathlib import Path
from zipfile import ZipFile
from zoneinfo import ZoneInfo

STUDY = "NCT05653388"
APP = Path(__file__).resolve().parent / "runtime/michigan.pyz"
LOCAL = "urn:pocketmd:research:course-binding-fixture"


@lru_cache(maxsize=1)
def _assets():
    with ZipFile(APP) as archive:
        return tuple(json.loads(archive.read("data/" + name + ".json")) for name in ("catalog", "rules"))


def catalog_version():
    return _assets()[0]["version"]


def reference_rule(criterion, protocol_sha256):
    _, rules = _assets()
    if rules["protocol_sha256"] != protocol_sha256:
        raise ValueError("Michigan evidence contracts belong to another protocol amendment.")
    rule = next((r for r in rules["criteria"] if r["id"] == criterion), None)
    if not rule:
        raise ValueError("No Michigan executable for this criterion.")
    return deepcopy(rule)


def _selectors():
    catalog, _ = _assets()
    focus = ["subject", "focus:Condition", "effectiveDateTime", "issued", "status"]
    mappings = {
        "lms": {"resource": "Condition", "value": "Condition.code or indexed mCODE histology extension",
                "context": ["subject", "indexed episode", "verificationStatus", "recordedDate"],
                "diagnosis_codes": deepcopy(catalog["diagnosis"])},
        "first_line_regimen": {"resources": ["CarePlan", "Observation", "MedicationRequest", "MedicationAdministration"],
                               "context": ["subject", "course addresses indexed Condition", "treatment line",
                                           "course inventory", "actual administrations and formulation"],
                               "drug_system": catalog["system"]},
    }
    for key in ("metastatic", "unresectable", "advanced_treatment_setting", "baseline_measurable"):
        context = focus if key in ("metastatic", "unresectable") else [*focus, "active CarePlan for this episode"]
        if key == "baseline_measurable":
            context = [*context, "same course cycle1_start observation", "assessment method"]
        mappings[key] = {"resource": "Observation", "system": LOCAL, "code": key,
                         "value": "Observation.valueBoolean", "meaning": catalog["local_observation_fields"][key],
                         "context": context}
    return mappings


def author_context(study):
    """Expose vocabulary and query capabilities independently of any criterion's reference tree."""
    if study != STUDY:
        return {}
    catalog, _ = _assets()
    return {
        "episode_evidence_catalog": {"version": catalog["version"], "facts": _selectors(), "drug_system": catalog["system"],
                                     "drug_products": deepcopy(catalog["products"]), "source_status": "synthetic_research"},
        "episode_rule_grammar": (
            "For this episode-based engine an executable Boolean expression is an object with exactly one "
            "operator, all or any, and a nonempty list of fact keys or nested expressions. Supply that "
            "same bare tree in draft and executable. Bind each distinct selected fact to its catalog key. "
            "Cite the protocol Word paragraph ID or numbered eligibility bullet. Other evidence needs remain open."
        ),
    }


def mapping(key):
    return {"key": key, "selector": _selectors()[key]}


def leaves(tree):
    if isinstance(tree, str):
        if tree not in _selectors():
            raise ValueError("Unknown Michigan episode fact.")
        return {tree}
    if not isinstance(tree, dict) or len(tree) != 1:
        raise ValueError("Invalid Michigan Boolean expression.")
    operator, children = next(iter(tree.items()))
    if operator not in {"all", "any"} or not isinstance(children, list) or not children:
        raise ValueError("Michigan Boolean groups require all or any and nonempty children.")
    return set().union(*(leaves(child) for child in children))


def normalize_tree(tree):
    """Compare Boolean conjunction/disjunction up to child order. Execute the sealed reference order."""
    leaves(tree)
    if isinstance(tree, str):
        return tree
    operator, children = next(iter(tree.items()))
    return {operator: sorted((normalize_tree(child) for child in children),
                             key=lambda item: json.dumps(item, sort_keys=True))}


def _cutoff(as_of, timezone_name):
    zone = ZoneInfo(timezone_name) if timezone_name else None
    if as_of is None:
        mark = datetime.now(zone).astimezone(zone)
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
        day = date.fromisoformat(as_of)
        return day, datetime.combine(day, time.max, tzinfo=zone or timezone.utc)
    else:
        mark = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        if mark.utcoffset() is None:
            raise ValueError("The screening timestamp needs a UTC offset.")
        if zone:
            mark = mark.astimezone(zone)
    return mark.date(), mark


def _frozen_bundle(bundle, cutoff):
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle" or bundle.get("type") != "collection":
        raise ValueError("Supply a normalized, patient-specific FHIR collection snapshot.")
    entries = []
    for entry in bundle.get("entry", []):
        resource = entry["resource"]
        times = [resource.get("meta", {}).get("lastUpdated"), resource.get("issued")]
        for event_time in times:
            if event_time and "T" in event_time:
                parsed = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
                if parsed.utcoffset() is None:
                    raise ValueError("Provide offset-bearing evidence availability timestamps.")
                if parsed > cutoff:
                    break
        else:
            entries.append(entry)
    return {**bundle, "entry": entries}


def run_episode(compiled, bundle, patient, episode, as_of, timezone_name=None):
    scope = {k: compiled[k] for k in ("study", "criterion_id", "protocol_sha256", "catalog_version", "rule_sha256")}
    scope.update(mode="synthetic_research", patient=patient, episode=episode, as_of=as_of,
                 as_of_precision="calendar_day", evidence=[], episode_catalog_version=_assets()[0]["version"])
    if not episode or not patient:
        return {**scope, "state":"MISSING_DATA", "reason":"Supply the patient and explicitly indexed cancer Condition episode."}
    try:
        day, cutoff = _cutoff(as_of, timezone_name)
        scope["screening_day"] = day.isoformat()
        if not as_of:
            scope["as_of"] = cutoff.isoformat()
        snap = _frozen_bundle(bundle, cutoff)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bundle.json"
            path.write_text(json.dumps(snap, allow_nan=False))
            result = subprocess.run([sys.executable, "-B", str(APP), "--bundle", str(path), "--patient", patient,
                                     "--episode", episode, "--criterion", compiled["criterion_id"], "--as-of",
                                     day.isoformat(), "--trace"], capture_output=True, text=True, timeout=30)
        if result.returncode:
            if "Query could not be evaluated" in result.stderr or "Supply a FHIR" in result.stderr:
                return {**scope, "state":"MISSING_DATA", "reason":result.stderr.strip()}
            return {**scope, "state":"VALIDATION_HOLD", "reason":"Michigan query process failed."}
        native = json.loads(result.stdout)
        key = compiled["criterion_id"]
        if native["protocol_sha256"] != scope["protocol_sha256"] or native["catalog_version"] != scope["episode_catalog_version"]:
            raise RuntimeError("Underlying Michigan source or catalog revision differs.")
        states = {**native["outcomes"], **native["holds"]}
        if set(states) != {key}:
            raise RuntimeError("The Michigan runtime returned unexpected criterion IDs.")
        evidence = sorted({ref for fact in native["facts"].values() for ref in fact["evidence"]})
        return {**scope, "state":states[key], "reason":"Evaluated the episode-specific Michigan rule.",
                "evidence":evidence, "requests":native["requests"], "facts":native["facts"],
                "source_locator":native["rules"][key]["source"],
                **({"course_trace":native["course_trace"]} if "course_trace" in native else {})}
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return {**scope, "state":"VALIDATION_HOLD", "reason":str(exc)}
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError) as exc:
        return {**scope, "state":"MISSING_DATA", "reason":"Evidence could not be verified: " + str(exc)}
