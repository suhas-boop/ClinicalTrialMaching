"""Research promotion of externally reviewed, previously unregistered age rules."""
import base64
from copy import deepcopy
from datetime import date

from compiler import canonical, digest, indexed, meaningful, require, research_mapping, screen, validate_model_draft

PATH = "reviewed_age_v1"
SCOPE = ("study", "criterion_id", "protocol_sha256", "catalog_version")
ANCHOR = "screening_run_local_date"
# Only this shipped, openly fictional source may use an automated fixture in place of a human.
QA_STUDY = "POCKETMD-SYNTHETIC-AGE"
QA_CRITERION = "POCKETMD-SYNTHETIC-AGE-I01"
QA_PROTOCOL_SHA256 = "a790fab4e66eff8254b7d3a57eb038eb4b503f3c9dc357b98f3dab3eadd0d9f3"


def _validate_source(packet):
    require(packet["catalog_version"] == screen.CATALOG_DATA["version"], "Catalog version mismatch.")
    if packet.get("source_mode") == "uploaded_pdf":
        from intake_source import validated_row
        row = validated_row(packet)
        require(packet["study"] not in screen.INVENTORY["studies"] and
                not any(x["id"] == packet["criterion_id"] for x in screen.INVENTORY["criteria"]),
                "A new upload cannot replace an inventoried study or criterion.")
    else:
        row = indexed(packet)
    require(row["extracted_text"] == packet["criterion_text"] and row["polarity"] == "inclusion",
            "Criterion text or inclusion polarity differs from the verified source.")
    if packet.get("synthetic_fixture") is True:
        require((packet.get("source_mode"), packet["study"], packet["criterion_id"], packet["protocol_sha256"])
                == ("uploaded_pdf", QA_STUDY, QA_CRITERION, QA_PROTOCOL_SHA256),
                "Only the exact shipped synthetic QA protocol may use a fictional reviewer.")
    require(packet["polarity"] == "inclusion", "This template only handles positive inclusion criteria.")
    require(packet["criterion_id"] not in screen.RULES, "Use the existing registered rule for this criterion.")


def _fixture(study, day, birth):
    stamp = day + "T09:00:00Z"
    patient = {"resourceType": "Patient", "id": "fixture"}
    if birth is not None:
        patient["birthDate"] = birth
    visit = {"resourceType": "Encounter", "id": "screen", "status": "in-progress",
             "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"},
             "subject": {"reference": "Patient/fixture"}, "period": {"start": stamp},
             "identifier": [{"system": "urn:pocketmd:demo:screening-study", "value": study}]}
    for resource in (patient, visit):
        resource["meta"] = {"versionId": "1", "lastUpdated": stamp}
    return {"resourceType": "Bundle", "type": "collection", "entry": [{"resource": resource} for resource in (patient, visit)]}


def _evaluate(study, rule, bundle, patient, encounter, as_of, timezone_name=None):
    cutoff = screen.screening_cutoff(as_of, timezone_name)
    evidence = []
    try:
        chart = screen.Snapshot(bundle, patient, study, encounter, cutoff)
        evidence = chart.evidence
        result = screen.eval_rule(chart, rule)
    except (AttributeError, ArithmeticError, LookupError, TypeError, ValueError) as exc:
        result = {"state": "MISSING_DATA", "reason": "Evidence could not be verified: " + str(exc), "evidence": evidence}
    return {**result, "as_of": cutoff}


def _controls(study, rule, cases):
    labels = {"above": "MET", "boundary": "MET", "below": "NOT_MET", "missing": "MISSING_DATA"}
    require(isinstance(cases, list) and len(cases) == 4 and {case["kind"] for case in cases} == set(labels),
            "Provide four frozen controls: above threshold, exact birthday, below threshold, and missing DOB.")
    results = []
    for case in cases:
        day, birth, kind = case["screening_date"], case["birth_date"], case["kind"]
        screening = date.fromisoformat(day)
        if birth is None:
            require(kind == "missing", "Only the missing-birthdate case may omit DOB.")
        else:
            dob = date.fromisoformat(birth)
            # Use an unambiguous birthday for the mandatory exact-boundary control.
            birthday = dob.replace(year=dob.year + rule["threshold"])
            if kind == "boundary":
                require(screening == birthday, "The boundary control must occur on the exact qualifying birthday.")
            elif kind == "below":
                require(dob <= screening < birthday, "The below-threshold control must precede the qualifying birthday.")
            else:
                require(kind == "above" and screening > birthday, "The above-threshold control must follow the birthday.")
        require(case["expected"] == labels[kind], "Control label disagrees with its registered meaning.")
        actual = _evaluate(study, rule, _fixture(study, day, birth), "fixture", "screen", day + "T12:00:00Z")["state"]
        require(actual == case["expected"], "Independent control failed: " + kind)
        results.append({"kind": kind, "expected": case["expected"], "actual": actual})
    return results


def _check_proof(packet, draft, review):
    _validate_source(packet)
    obligations, questions, bound, gaps = validate_model_draft(packet, draft)
    for key in SCOPE:
        require(review.get(key) == packet[key], "Review differs from source scope: " + key)
    require(review.get("decision") == "approve_research_rule" and review.get("independent_source_review") is True,
            "An independent, external source review for research execution is required.")
    expected_reviewer = "synthetic_test_fixture" if packet.get("synthetic_fixture") is True else "human"
    require(review.get("reviewer_type") == expected_reviewer and all(meaningful(review.get(k)) for k in
            ("authority", "decision_date", "source_reference")), "Provide reviewer identity, date, type, and source.")
    date.fromisoformat(review["decision_date"])
    require(review.get("draft_sha256") == digest(draft) and review.get("answers_sha256") == digest(packet["answers"]),
            "Reviewer did not approve this exact draft and feedback revision.")
    require(review.get("criterion_text") == packet["criterion_text"] and review.get("time_anchor") == ANCHOR,
            "Source text or screening time anchor differs.")
    require(draft["disposition"] == "EXECUTABLE" and not questions and not gaps,
            "Resolve open protocol or binding gaps before promotion.")
    rule = draft["executable"]
    require(isinstance(rule, dict) and set(rule) == {"fact", "operator", "threshold"}
            and rule["fact"] == "age" and rule["operator"] == "ge" and type(rule["threshold"]) is int
            and rule["threshold"] > 0, "Only age in completed years >= a positive integer is supported.")
    structured = draft["draft"]
    if isinstance(structured, dict) and set(structured) == {"kind", "rule"} and structured["kind"] == "registered_rule":
        structured = structured["rule"]
    require(canonical(rule) == canonical(structured) == canonical(review["reference_rule"]),
            "Draft expression, executable, and independent rule must agree exactly.")
    ids = [item["id"] for item in obligations]
    require(sorted(ids) == sorted(review["covered_obligation_ids"]),
            "Independent review must cover every source obligation.")
    bindings = draft["bindings"]
    require(bound == {"age"} and len(bindings) == 1 and bindings[0].get("fact") == "age", "Expected one bound age fact.")
    query = research_mapping("age")
    require(query["selector"]["status"] == "FHIR_native" and query["selector"]["value"] == "Patient.birthDate",
            "The native DOB selector differs from the reviewed contract.")
    require("queries" not in draft or canonical(draft["queries"]) == canonical([query]), "Draft query mismatch.")
    results = _controls(packet["study"], rule, review["control_cases"])
    return rule, query, results


def compile_reviewed(packet, draft, review):
    """The caller supplies the independent review through a separate trusted input, never from the LLM."""
    scope = {k: packet.get(k) for k in SCOPE}
    base = {**scope, "mode": "synthetic_research", "promotion_path": PATH, "questions": [], "binding_gaps": []}
    try:
        require(isinstance(review, dict) and isinstance(draft, dict), "Review and draft objects are required.")
        catalog = packet["catalog"]
        require(catalog["version"] == scope["catalog_version"] and
                canonical([m for m in catalog["mappings"] if m.get("key") == "age"]) == canonical([screen.CATALOG["age"]]),
                "The author packet must contain the native age contract.")
        rule, query, results = _check_proof(packet, draft, review)
        source = {k: packet[k] for k in (*SCOPE, "criterion_text", "polarity", "answers")}
        if packet.get("source_mode") == "uploaded_pdf":
            # Store the PDF once in the proof, without duplicating extracted text and rendered images.
            source.update({k: packet[k] for k in ("source_mode", "intake_manifest", "protocol_attachment")})
            source["author_packet_sha256"] = digest(packet)
        proof = deepcopy({"packet": source, "draft": draft, "review": review})
        return {**base, "state": "READY", "reason": "Independent reference and four synthetic controls matched.",
                "executable": dict(rule), "rule_sha256": digest(rule), "author_sha256": digest(draft),
                "polarity": "inclusion", "queries": [query], "controls": results,
                "promotion_proof": proof, "review_sha256": digest(proof)}
    except (LookupError, TypeError, ValueError, OverflowError, AttributeError) as exc:
        return {**base, "state": "VALIDATION_HOLD", "reason": str(exc), "executable": None}


def evaluate_reviewed(compiled, bundle, patient, encounter, as_of=None, *, timezone_name=None):
    meta = {k: compiled.get(k) for k in (*SCOPE, "rule_sha256", "mode")}
    meta.update(patient=patient, encounter=encounter, as_of=as_of)
    try:
        require(compiled.get("state") == "READY" and compiled.get("promotion_path") == PATH, "Reviewed release required.")
        proof = compiled["promotion_proof"]
        require(digest(proof) == compiled["review_sha256"] and all(proof["packet"][k] == meta[k] for k in SCOPE),
                "Compiled review provenance changed.")
        packet = proof["packet"]
        if packet.get("source_mode") == "uploaded_pdf":
            from intake_source import build_intake_packet
            raw = base64.b64decode(packet["protocol_attachment"]["data_base64"], validate=True)
            rebuilt = build_intake_packet(packet["intake_manifest"], raw, packet["answers"])
            require(digest(rebuilt) == packet["author_packet_sha256"] and
                    all(rebuilt[k] == packet[k] for k in SCOPE), "External protocol packet changed.")
            packet = rebuilt
        rule, query, _ = _check_proof(packet, proof["draft"], proof["review"])
        require(digest(rule) == meta["rule_sha256"] and canonical(rule) == canonical(compiled["executable"])
                and canonical([query]) == canonical(compiled["queries"]), "Compiled executable or binding changed.")
        return {**meta, **_evaluate(meta["study"], rule, bundle, patient, encounter, as_of, timezone_name)}
    except (LookupError, TypeError, ValueError, OverflowError, AttributeError) as exc:
        return {**meta, "state": "VALIDATION_HOLD", "reason": str(exc), "evidence": []}
