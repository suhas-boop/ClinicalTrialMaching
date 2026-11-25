"""Historical PH-L19TNFDOX2 v6 criterion checks on a synthetic, normalized FHIR bundle.

Public API: evaluate(criterion, bundle, anchors). Each returned state is relative to
one criterion. A MET exclusion means the patient is clear of that one exclusion.
Only the uploaded v6 historical protocol is supported. The anchor packet must
come from a trusted normalization layer that validates source document signatures
and confirms patient, study version, actual randomization and first dose, actual
consent signature, and the interval of the screening period. This module checks
the packet/record linkage, author, source version, and timing; it cannot validate
a site identity or digital signature. A merely planned first dose is not accepted.
This provides retrospective replay. Only patient evidence already available before
randomization can support the result. Timestamps in this fixture use UTC instants.
"""
from datetime import datetime, timedelta
from decimal import Decimal
import json
import re

STUDY = "PH-L19TNFDOX2"
VERSION = "6.0"
RULES = ["I05", "E10", "E11", "E15"]
LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"
CODES = {"I05": "89247-1", "E11": "6301-6", "E15": "8806-2"}
STUDY_SYSTEM = "urn:pocketmd:research:trial-version"
LIVER = {"1742-6":{"U/L"}, "1920-8":{"U/L"}, "2324-2":{"U/L"},
         "6768-6":{"U/L"}, "1975-2":{"mg/dL", "umol/L"}}
DECIMAL_UNIT = {"1", "{INR}"}
REF_PATTERN = re.compile(r"^[A-Za-z]+/[A-Za-z0-9.-]{1,64}/_history/[A-Za-z0-9.-]{1,64}$")


class Hold(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise Hold(reason)


def dt(value):
    require(isinstance(value, str) and "T" in value and
            re.search(r"(?:Z|[+]00:00)$", value), "Provide full UTC instants.")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(result.utcoffset() == timedelta(0), "Provide normalized UTC instants.")
    return result


def ref(obj):
    return f"{obj['resourceType']}/{obj['id']}/_history/{obj['meta']['versionId']}"


def coding(r, system):
    return {c["code"] for c in r.get("coding", []) if c.get("system") == system and c.get("code")}


def exact_quantity(q, units, upper=None):
    require(isinstance(q, dict) and q.get("system") == UCUM and q.get("code") in units
            and "comparator" not in q, "Need an exact quantity with the correct UCUM unit.")
    require(type(q.get("value")) in (int, float, Decimal), "Need a numeric quantity.")
    result = Decimal(str(q["value"]))
    require(result.is_finite() and result >= 0 and (upper is None or result <= upper),
            "Quantity is outside its valid measurement domain.")
    return result


def lab_range(obs, units):
    ranges = obs.get("referenceRange", [])
    require(len(ranges) == 1, "Need one applicable result-specific upper reference limit.")
    rr = ranges[0]
    require(not ({"type", "appliesTo", "age", "text"} & rr.keys()),
            "Conditional or unstructured reference intervals need a qualified selection.")
    high = exact_quantity(rr["high"], units)
    require(high > 0, "Upper reference limit must be positive.")
    return high


def result(criterion, status, reason, refs=()):
    return {"criterion":criterion, "study":STUDY, "version":VERSION, "state":status,
            "reason":reason, "evidence":sorted(set(refs)), "use":"historical_synthetic_replay"}


def index_resources(bundle):
    require(bundle.get("resourceType") == "Bundle" and bundle.get("type") == "collection",
            "Supply a normalized FHIR collection.")
    by_ref = {}
    ids = set()
    for entry in bundle["entry"]:
        r = entry["resource"]
        key = ref(r)
        require(REF_PATTERN.fullmatch(key) and key.split("/_history/")[0] not in ids,
                "Supply one as-of version per resource.")
        require(not r.get("implicitRules") and not r.get("modifierExtension"),
                "Resource modifier semantics need review.")
        ids.add(key.split("/_history/")[0])
        by_ref[key] = r
    return by_ref


def attestation(norm, records, patient, cutoff, purpose, scope):
    """External verified-signature precondition, grounded in one versioned local source."""
    require(norm.get("signature_verified") is True and norm.get("purpose") == purpose
            and norm.get("scope") == scope, "Need a verified, correctly scoped source attestation.")
    d = records.get(norm["reference"], {})
    require(d.get("resourceType") == "DocumentReference" and d.get("status") == "current"
            and d.get("docStatus") == "final" and d.get("subject",{}).get("reference") == patient,
            "Wrong patient, source version, or document status.")
    require(any(i.get("system") == STUDY_SYSTEM and i.get("value") == STUDY + "|" + VERSION
                for i in d.get("identifier",[])), "Source belongs to a different study or version.")
    signer = norm.get("signer", "")
    require(isinstance(signer, str) and signer.startswith("Practitioner/") and
            signer in [item.get("reference") for item in d.get("author",[])],
            "Named attester must match the author of the versioned document.")
    require(dt(d["date"]) <= cutoff and dt(d["meta"]["lastUpdated"]) <= cutoff,
            "Referenced document was unavailable at the evaluation cutoff.")
    return ref(d)


def parse_anchors(a, records):
    require(a.get("study") == STUDY and a.get("version") == VERSION and
            a.get("purpose") == "historical_synthetic_replay", "Only historical v6 research use is supported.")
    require(a.get("anchor_mode") == "verified_actual", "Actual treatment and randomization times are required.")
    patient = a["patient"]
    require(re.fullmatch(r"Patient/[A-Za-z0-9.-]{1,64}", patient), "Supply one patient id.")
    consent, start, end, rand, dose, as_of = (dt(a[key]) for key in
            ("consent_signed","screening_start","screening_end","randomization","first_dose","as_of"))
    require(consent <= start <= end <= rand <= dose <= as_of and end - start <= timedelta(days=14)
            and dose - rand <= timedelta(days=7),
            "Verify the historical screening timeline and randomization-to-dose interval.")
    scope = "|".join([a[k] for k in ("patient", "encounter", "consent_signed", "screening_start",
                                      "screening_end", "randomization", "first_dose")])
    timeline_ref = attestation(a["anchor_attestation"],records,patient,as_of,"actual-screening-anchors",scope)
    require(dt(records[timeline_ref]["date"]) >= dose, "Actual first-dose documentation precedes its event.")
    encounter = records.get(a["encounter"], {})
    require(encounter.get("resourceType") == "Encounter" and encounter.get("subject",{}).get("reference") == patient
            and encounter.get("status") in {"finished","in-progress"}
            and any(i.get("system") == STUDY_SYSTEM and i.get("value") == STUDY + "|" + VERSION
                    for i in encounter.get("identifier",[])), "Study screening encounter is unverified.")
    require(dt(encounter["period"]["start"]) == start and dt(encounter["period"]["end"]) == end
            and dt(encounter["meta"]["lastUpdated"]) <= as_of,"Encounter timing differs from the anchor packet.")
    return patient, consent, start, end, rand, dose, timeline_ref


def measure(rule, obs, concept):
    require("dataAbsentReason" not in obs, "Observation lacks a documented value.")
    fields = {k for k in obs if k.startswith("value")}
    if rule == "I05":
        require(fields == {"valueInteger"} and type(obs["valueInteger"]) is int and 0 <= obs["valueInteger"] <= 5,
                "Need a valid integer ECOG score.")
        return obs["valueInteger"] <= 1
    require(fields == {"valueQuantity"}, "Need a single quantified measurement.")
    if rule == "E10":
        unit = obs["valueQuantity"].get("code")
        number = exact_quantity(obs["valueQuantity"], LIVER[concept])
        return number < Decimal("1.5") * lab_range(obs, {unit})
    if rule == "E11":
        # Fraction arithmetic by cross multiplication avoids division and rounding at the threshold.
        return exact_quantity(obs["valueQuantity"],DECIMAL_UNIT) <= Decimal("1.5") * lab_range(obs, DECIMAL_UNIT)
    return exact_quantity(obs["valueQuantity"],{"%"},100) >= Decimal("50")


def eligible_observation(rule, obs, a, records, patient, consent, start, end, rand, dose):
    if obs.get("subject",{}).get("reference") != patient or obs.get("status") in {"entered-in-error","cancelled"}:
        return None
    loincs = coding(obs.get("code",{}), LOINC)
    expected = LIVER.keys() if rule == "E10" else {CODES[rule]}
    concepts = loincs & expected
    if not concepts:
        return None
    require(len(loincs) == 1,"Conflicting LOINC concepts.")
    concept = next(iter(concepts))
    require({k for k in obs if k.startswith("effective")} == {"effectiveDateTime"},
            "Need an unambiguous measurement time.")
    when = dt(obs["effectiveDateTime"])
    if when > rand:
        return None
    refs = [ref(obs)]
    if when < consent:
        # Only the ECHO has a pre-consent instrumental-assessment path among these three rules.
        if rule != "E15" or rand - when > timedelta(weeks=4):
            return None
        suit = a.get("historical_echo",{}).get(ref(obs))
        require(suit, "Pre-consent ECHO requires documented suitability for screening.")
        sufficiency_ref = attestation(suit,records,patient,rand,"pre-consent-echo-sufficient",ref(obs))
        require(dt(records[sufficiency_ref]["date"]) >= when, "Suitability statement predates its ECHO.")
        refs.append(sufficiency_ref)
    else:
        if not (start <= when <= end and when < rand and rand-when <= timedelta(days=14)
                and dose-when <= timedelta(days=21)):
            return None
        if obs.get("encounter",{}).get("reference") not in {a["encounter"],a["encounter"].split("/_history/")[0]}:
            return None
        require(when > consent,"Consent must precede the screening procedure; resolve tied times.")
    if dt(obs["issued"]) > rand or dt(obs["meta"]["lastUpdated"]) > rand:
        return None
    require(obs.get("status") in {"final","amended","corrected"} and when <= dt(obs["issued"]),
            "A completed result and valid release time are required.")
    docs = obs.get("derivedFrom",[])
    require(len(docs) == 1, "Need one source report for this normalized result.")
    doc_ref = docs[0]["reference"]
    doc = records.get(doc_ref,{})
    require(doc.get("resourceType") == "DocumentReference" and doc.get("status") == "current"
            and doc.get("docStatus") == "final" and doc.get("subject",{}).get("reference") == patient
            and when <= dt(doc["date"]) <= rand and dt(doc["meta"]["lastUpdated"]) <= rand,
            "Source report version was unavailable or belongs to another patient.")
    refs.append(doc_ref)
    if rule in {"E10", "E11"}:
        sp_ref = obs.get("specimen", {}).get("reference")
        material = records.get(sp_ref,{})
        types = coding(material.get("type",{}),"http://terminology.hl7.org/CodeSystem/v2-0487")
        permitted = {"PPP"} if rule == "E11" else {"SER","PLAS"}
        require(material.get("resourceType") == "Specimen" and material.get("status") in {None,"available"}
                and material.get("subject",{}).get("reference") == patient
                and len(types) == 1 and types.issubset(permitted)
                and dt(material["meta"]["lastUpdated"]) <= rand,
                "Verify patient, specimen type and version for this assay.")
        refs.append(sp_ref)
    return concept,measure(rule,obs,concept),refs


def evaluate(criterion, bundle, anchors):
    if criterion not in RULES:
        return result(criterion,"REVIEW_REQUIRED","Unsupported criterion.")
    if anchors.get("study") != STUDY or anchors.get("version") != VERSION or anchors.get("purpose") != "historical_synthetic_replay":
        return result(criterion,"REVIEW_REQUIRED","This mapping is restricted to the supplied historical protocol v6.")
    refs = []
    try:
        records = index_resources(bundle)
        patient, consent, start, end, rand, dose, anchor_ref = parse_anchors(anchors,records)
        refs.extend([anchor_ref,anchors["encounter"]])
        decisions = {}
        for obs in records.values():
            if obs["resourceType"] != "Observation":
                continue
            decision = eligible_observation(criterion,obs,anchors,records,patient,consent,start,end,rand,dose)
            if decision:
                concept, passed, supporting = decision
                decisions.setdefault(concept,set()).add(passed)
                refs.extend(supporting)
        if not decisions:
            return result(criterion,"MISSING_DATA","No qualifying source-linked measurement.",refs)
        # Each analyte is evaluated against its own ULN. An unequivocal failing branch of
        # the disjunctive exclusion is decisive even if a different analyte was not measured.
        if any(values == {False} for values in decisions.values()):
            return result(criterion,"NOT_MET","A qualifying measurement establishes the threshold condition.",refs)
        if any(len(values) > 1 for values in decisions.values()):
            return result(criterion,"MISSING_DATA","Qualifying measurements disagree across the decision boundary.",refs)
        if criterion == "E10" and set(decisions) != set(LIVER):
            return result(criterion,"MISSING_DATA","Complete the five-analyte liver panel before clearing this exclusion.",refs)
        return result(criterion,"MET","All required source-linked measurements meet the criterion.",refs)
    except (KeyError,TypeError,ValueError,AttributeError,ArithmeticError) as error:
        return result(criterion,"MISSING_DATA","Verify the evidence: " + str(error),refs)


def run_checks():
    """Replay the bundled synthetic qualification tests."""
    from test_philogen import run_checks as replay
    return replay()


if __name__ == "__main__":
    print(json.dumps(run_checks(), indent=2))
