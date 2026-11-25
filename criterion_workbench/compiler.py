"""Compile source-locked authoring drafts against the four-site research runtime."""

import hashlib
import json
import re
import sys
from pathlib import Path
from copy import deepcopy

RUNTIME = Path(__file__).resolve().parent / "runtime"
sys.path.insert(0, str(RUNTIME))
import screen
import michigan_adapter as michigan
from onboarding import test_cycle, validate as validate_profile


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def meaningful(value):
    return isinstance(value, str) and bool(value.strip())


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def indexed(packet):
    criterion = packet.get("criterion_id")
    if packet.get("source_mode") == "uploaded_pdf":
        require(packet.get("study") not in screen.INVENTORY["studies"] and
                not any(r["id"] == criterion for r in screen.INVENTORY["criteria"]),
                "An external study or criterion cannot shadow indexed scope.")
        require(packet.get("catalog_version") == screen.CATALOG_DATA["version"], "Catalog version mismatch.")
        from intake_source import validated_row
        row = validated_row(packet)
        require(row["id"] == criterion and row["study"] == packet.get("study") and
                row["polarity"] == packet.get("polarity"), "Uploaded source row and packet scope differ.")
        return row
    row = next((row for row in screen.INVENTORY["criteria"] if row["id"] == criterion), None)
    require(row and row["study"] == packet.get("study"), "Study and criterion must match the inventory.")
    source = screen.INVENTORY["studies"][row["study"]]
    require(packet.get("protocol_sha256") == source["protocol_sha256"], "Protocol amendment mismatch.")
    require(packet.get("catalog_version") == screen.CATALOG_DATA["version"], "Catalog version mismatch.")
    require(packet.get("polarity", row["polarity"]) == row["polarity"], "Criterion polarity mismatch.")
    return row


def research_mapping(key, study=None):
    if study == michigan.STUDY:
        return michigan.mapping(key)
    entry = screen.CATALOG.get(key)
    if entry is not None:
        return {"key": key, "selector": deepcopy(entry)}
    for namespace in ("prescreen_assays", "agreement_forms"):
        if key in screen.CATALOG_DATA.get(namespace, {}):
            return {"key": key, "selector": deepcopy(screen.CATALOG_DATA[namespace][key])}
    raise ValueError("Unknown evidence catalog key: " + str(key))


def rule_keys(rule):
    """Include evidence selected conditionally by the sealed runtime operators."""
    keys = set(rule.get("facts", ())) | set(rule.get("minimum", {}))
    keys.update(rule[name] for name in ("fact", "agreement", "contract") if name in rule)
    if rule.get("age_routing"):
        keys.update(("age", "lansky", "karnofsky"))
    if rule.get("acquisitions") == "screening_and_history":
        keys.add("long_qt_history")
    if rule.get("kind") == "respondent_agreement":
        keys.add("age")
    return keys


def cites_criterion(obligations, row):
    """Verify a target-page or numbered section anchor; passage meaning needs independent review."""
    citations = " ".join(o["source_locator"].lower() for o in obligations)
    bounds = row.get("pdf_pages")
    if not bounds:
        paragraph = row.get("locator", {}).get("word_paragraph_id")
        return bool((paragraph and paragraph.lower() in citations) or row.get("section", "").lower() in citations)
    cited_pages = re.findall(r"\b(?:p{1,2}\.|pages?\s*|p\s+)\s*(\d+)(?:\s*[-–—]\s*(\d+))?", citations)
    if cited_pages:
        return any(int(low) <= bounds[-1] and int(high or low) >= bounds[0] for low, high in cited_pages)
    section = re.search(r"\d+(?:\.\d+)+", row.get("section", ""))
    return bool(section and re.search(r"(?:§|section)\s*" + re.escape(section.group()) + r"(?![\d.])", citations))


def semantic_plan(rule):
    require(isinstance(rule, dict), "A deterministic executable must be a rule object.")
    return {k: v for k, v in rule.items() if k != "context"}


def has_open_operand(node):
    if isinstance(node, list):
        return any(has_open_operand(x) for x in node)
    if isinstance(node, dict):
        if any(str(node.get(k, "")).upper() in {"UNRESOLVED", "UNBOUND", "PENDING", "UNKNOWN_BINDING"}
               for k in ("state", "status")):
            return True
        return any(has_open_operand(value) for value in node.values())
    return False


def validate_model_draft(packet, draft):
    """Validate author identity, source citations, and binding records against the fixed catalog.

    The caller supplies a source-verified packet with study, criterion, amendment,
    polarity and catalog version; independently verify that packet before calling.
    """
    require(isinstance(draft, dict), "Author response must be a JSON object.")
    for k in ("criterion_id", "protocol_sha256", "catalog_version"):
        require(draft.get(k) == packet[k], "Author response mismatch for " + k)
    require(draft.get("study", packet["study"]) == packet["study"], "Author study differs from the source.")
    require(draft.get("polarity", packet["polarity"]) == packet["polarity"], "Author polarity differs from the source.")
    if draft.get("disposition") == "EXECUTABLE":
        answers = packet.get("answers", [])
        require(isinstance(answers, list), "Reviewer answers must be a list.")
        expected_ids = []
        for answer in answers:
            require(isinstance(answer, dict) and meaningful(answer.get("question_id")),
                    "Every scoped reviewer answer needs a stable question ID.")
            for field in ("study", "criterion_id", "protocol_sha256"):
                require(answer.get(field, packet[field]) == packet[field],
                        "Reviewer answer belongs to a different source scope.")
            expected_ids.append(answer["question_id"])
        applied_ids = draft.get("applied_question_ids", [])
        require(isinstance(applied_ids, list) and all(meaningful(i) for i in applied_ids) and
                len(set(applied_ids)) == len(applied_ids) and len(set(expected_ids)) == len(expected_ids) and
                set(applied_ids) == set(expected_ids),
                "applied_question_ids must exactly cover all scoped reviewer answers.")
    obligations = draft.get("obligations")
    require(isinstance(obligations, list) and obligations, "Source-linked obligations are required.")
    for obligation in obligations:
        require(isinstance(obligation, dict) and all(meaningful(obligation.get(k))
                for k in ("id", "statement", "source_locator")), "Each obligation needs an ID, statement and source locator.")
    require(len({o["id"] for o in obligations}) == len(obligations), "Duplicate obligation IDs.")
    require(isinstance(draft.get("draft"), dict) and draft["draft"], "A structured rule draft is required.")
    questions = draft.get("clinical_questions")
    require(isinstance(questions, list), "clinical_questions must be an array.")
    require(all(isinstance(q, dict) and meaningful(q.get("question")) for q in questions),
            "Each clinical question needs question text.")
    bindings = draft.get("bindings")
    require(isinstance(bindings, list), "bindings must be an array.")
    keys, gaps = set(), []
    for item in bindings:
        require(isinstance(item, dict) and meaningful(item.get("fact")), "A binding must name the evidence fact.")
        key, status = item.get("catalog_key"), item.get("status")
        if status == "BOUND":
            require(meaningful(key), "A bound evidence fact must reference a registered catalog key.")
            research_mapping(key, packet["study"])
            require(key not in keys, "Duplicate binding for " + key)
            keys.add(key)
        else:
            require(status in ("UNBOUND", "SUPPLIED_RUNTIME_CONTEXT") and key is None,
                    "Unsupported evidence binding status or key.")
            if status == "UNBOUND":
                gaps.append(item)
    return obligations, questions, keys, gaps


def registered_reference(row, protocol_sha256):
    if row["study"] == michigan.STUDY:
        reference = michigan.reference_rule(row["id"], protocol_sha256)
        require(reference["source"]["locator"] == row["locator"], "Michigan source paragraph mismatch.")
        rule = reference["expression"]
        return rule, michigan.leaves(rule), michigan.normalize_tree
    rule = screen.RULES.get(row["id"])
    require(rule is not None, "No registered executable for this amendment and criterion. A new reference rule and equivalence tests are required.")
    return rule, rule_keys(rule), semantic_plan


def compile_draft(packet, draft):
    """READY means executable on synthetic research snapshots using a registered rule."""
    scope = {k: packet.get(k) for k in ("study", "criterion_id", "protocol_sha256", "catalog_version")}
    base = {**scope, "mode": "synthetic_research", "questions": [], "binding_gaps": []}
    try:
        row = indexed(packet)
        obligations, questions, keys, gaps = validate_model_draft({**packet, "polarity": row["polarity"]}, draft)
        base.update(questions=deepcopy(questions), binding_gaps=deepcopy(gaps), obligations=deepcopy(obligations), polarity=row["polarity"],
                    author_sha256=digest(draft), source_pages=row.get("pdf_pages", []),
                    answers_sha256=digest(packet.get("answers", [])),
                    applied_question_ids=deepcopy(draft.get("applied_question_ids", [])))
        disposition = draft.get("disposition")
        require("executable" in draft, "Explicit executable or null is required.")
        if questions or gaps:
            expected = ("PROTOCOL_AND_BINDING_REVIEW" if questions and gaps else
                        "PROTOCOL_REVIEW" if questions else "BINDING_REVIEW")
            require(disposition == expected and draft["executable"] is None,
                    "Author disposition, questions, evidence gaps and executable disagree.")
            return {**base, "state": expected, "reason": "Authoring review is open.", "executable": None}
        require(disposition == "EXECUTABLE", "A review disposition requires an identified question or evidence gap.")
        require(cites_criterion(obligations, row), "No obligation cites the indexed criterion page or section.")
        require(not has_open_operand(draft["draft"]), "Draft includes an unresolved operand.")
        registered, expected_keys, normalize_plan = registered_reference(row, scope["protocol_sha256"])
        proposed = normalize_plan(draft["executable"])
        require(canonical(proposed) == canonical(normalize_plan(registered)), "Executable differs from registered source-locked semantics.")
        tree = draft["draft"]
        if set(tree) == {"kind", "rule"} and tree["kind"] == "registered_rule":
            tree = tree["rule"]
        require(canonical(normalize_plan(tree)) == canonical(proposed), "Structured draft and executable differ.")
        require(expected_keys == keys, "Bindings must cover exactly the evidence selected by this rule.")
        selectors = [research_mapping(key, row["study"]) for key in sorted(keys)]
        if row["study"] == michigan.STUDY:
            base["source_locator"] = row["locator"]
            base["episode_catalog_version"] = michigan.catalog_version()
        if "queries" in draft:
            require(canonical(draft["queries"]) == canonical(selectors), "Supplied queries differ from registered selectors.")
        return {**base, "state": "READY", "reason": "Matched the registered synthetic-research rule and catalog selectors.",
                "executable": deepcopy(registered), "rule_sha256": digest(registered), "queries": selectors}
    except (LookupError, TypeError, ValueError) as exc:
        return {**base, "state": "VALIDATION_HOLD", "reason": str(exc), "executable": None}


def evaluate(compiled, bundle, patient, encounter, as_of=None, *, onboarding=None, timezone_name=None, episode=None):
    """Evaluate one compiled criterion; authoring and binding holds cannot become patient outcomes."""
    context = {k: compiled.get(k) for k in ("study", "criterion_id", "protocol_sha256", "catalog_version", "rule_sha256")}
    context.update(patient=patient, encounter=encounter, as_of=as_of, mode="synthetic_research")
    def result(state, reason, evidence=()):
        return {**context, "state": state, "reason": reason, "evidence": list(evidence)}
    if compiled.get("state") != "READY":
        return result(compiled.get("state", "VALIDATION_HOLD"), compiled.get("reason", "Rule has no release."))
    try:
        row = indexed(compiled)
        rule, keys, _ = registered_reference(row, compiled["protocol_sha256"])
        require(rule and digest(rule) == compiled.get("rule_sha256") and canonical(rule) == canonical(compiled.get("executable")),
                "Compiled rule differs from the registered executable.")
        require(canonical(compiled.get("queries")) == canonical([research_mapping(k, row["study"]) for k in sorted(keys)]),
                "Compiled selectors differ from the registered selectors.")
        if onboarding is not None:
            profile = validate_profile(onboarding, row["study"])
            timezone_name = timezone_name or profile["timezone"]
        if row["study"] == michigan.STUDY:
            require(compiled.get("episode_catalog_version") == michigan.catalog_version(), "Michigan catalog revision mismatch.")
            return michigan.run_episode(compiled, bundle, patient, episode, as_of, timezone_name)
        cutoff = screen.screening_cutoff(as_of, timezone_name)
        context["as_of"] = cutoff
        cycle = test_cycle(profile, cutoff) if onboarding is not None else None
    except (TypeError, ValueError, LookupError) as exc:
        return result("VALIDATION_HOLD", str(exc))
    evidence = []
    try:
        chart = screen.Snapshot(bundle, patient, row["study"], encounter, cutoff)
        evidence = chart.evidence
        if rule.get("screen_before_cycle_start") and not cycle:
            return result("MISSING_DATA", "Supply cycle 1 day 1 to verify the screening window.", evidence)
        decision = screen.eval_rule(chart, rule, cycle, timezone_name)
    except (ValueError, TypeError, LookupError, ArithmeticError, AttributeError) as exc:
        return result("MISSING_DATA", "Evidence could not be verified: " + str(exc), evidence)
    workflow = rule.get("assessment_workflow")
    if workflow:
        decision["assessment_workflow"] = {**workflow, "status": {
            "MET": "COMPLETED", "NOT_MET": "COMPLETED", "INVESTIGATOR_ACTIONS": "ACTION_REQUIRED",
            "MISSING_DATA": "VERIFY_EVIDENCE"}.get(decision["state"], decision["state"])}
    return {**context, **decision}
