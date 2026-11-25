"""Review a typed PocketMD rule pack against a normalized FHIR snapshot."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

RELEASE = Path(__file__).resolve().parents[1] / "eight_rules" / "release"
sys.path.insert(0, str(RELEASE))
from bindings import Snapshot, contract
from eligibility_engine import evaluate, validate
from measurement_families import FAMILIES

DECIDED = {"MET", "NOT_MET", "NOT_APPLICABLE"}
ROUTES = {"MISSING_DATA": "retrieve_record", "INVESTIGATOR_ACTIONS": "investigator",
          "PATIENT_SURVEY": "patient", "STUDY_ACTION": "study_team",
          "BINDING_HOLD": "engineering", "AUTHORING_HOLD": "protocol_review"}


def unresolved(node, rule, snapshot):
    """Skip resolved branches and postpone conditional branches until the gate is known."""
    state = evaluate({"expression": node, "facts": rule["facts"]}, snapshot)["state"]
    if state in DECIDED:
        return
    if "fact" in node:
        yield node["fact"], state
    elif "same_measurement" in node:
        if state == "MISSING_DATA":
            yield FAMILIES[node["family"]]["request"], state
        else:
            # Engineering issues retain their original contract identifier.
            for form in node["same_measurement"]:
                yield from unresolved(form,rule,snapshot)
    elif "hold" in node:
        yield node["hold"], "AUTHORING_HOLD"
    elif "if" in node:
        gate = evaluate({"expression": node["if"], "facts": rule["facts"]}, snapshot)["state"]
        child = node["then"] if gate == "MET" else node["else"] if gate == "NOT_MET" else node["if"]
        yield from unresolved(child, rule, snapshot)
    else:
        children = [node["not"]] if "not" in node else node.get("all",node.get("any",[]))
        for child in children:
            yield from unresolved(child, rule, snapshot)


def screen(rules, packet, study, version):
    ctx = packet["context"]
    snap = Snapshot(packet["bundle"], ctx, study, version)
    return screen_snapshot(rules, snap, ctx, study, version)


def screen_snapshot(rules, snap, ctx, study, version):
    results, requests = {}, {}
    if ctx.get("source_scope") == "multiple_subjects":
        # A patient identifier created for a group vignette does not identify a person.
        # Protocol questions still apply regardless of which individual is selected.
        group_id = hashlib.sha256(json.dumps([ctx["patient"], ctx.get("source_sha256"), "identify_subject"]).encode()).hexdigest()
        for cid, rule in rules.items():
            validate(rule)
            definition = rule["expression"]
            if isinstance(definition, dict) and set(definition) == {"hold"}:
                route, state, request = "protocol_review", "AUTHORING_HOLD", definition["hold"]
                identifier = hashlib.sha256(json.dumps([study, version, route, request]).encode()).hexdigest()
            else:
                route, state = "identify_subject", "SOURCE_SCOPE_HOLD"
                request = "Which individual in this group note is the screening subject? Supply their individual record."
                identifier = group_id
            results[cid] = dict(state=state, reason=request, evidence=[], facts={}, partial_evidence=[])
            requests.setdefault(identifier, dict(id=identifier, route=route, request=request, criteria=[]))["criteria"].append(cid)
        pending = list(requests.values())
        return dict(criteria=results, requests=pending, work=work_counts(results, pending))
    for cid, rule in rules.items():
        validate(rule)
        verdict = evaluate(rule, snap)
        verdict["partial_evidence"] = sorted({ref for f in verdict["facts"].values()
                                               if f["state"] == "AVAILABLE" for ref in f["evidence"]})
        results[cid] = verdict
        if verdict["state"] in DECIDED:
            continue
        node = rule["expression"]
        if "applies" in rule:
            gate = evaluate({"expression":rule["applies"],"facts":rule["facts"]},snap)
            if gate["state"] != "MET":
                node = rule["applies"]
        for name, state in unresolved(node, rule, snap):
            route = ROUTES[state]
            spec = rule["facts"].get(name) if state != "AUTHORING_HOLD" else None
            requirement = contract(spec) if spec else name
            scope = [study,version,route,requirement]
            if route not in {"protocol_review","engineering"}:
                scope.extend([ctx["patient"],ctx["episode"],ctx["encounter"],ctx["as_of"]])
            key = hashlib.sha256(json.dumps(scope).encode()).hexdigest()
            item = requests.setdefault(key, {"id":key,"route":route,"request":spec["scope"] if spec else name,"criteria":[]})
            if route == "engineering":
                item["contract"] = requirement
            if cid not in item["criteria"]:
                item["criteria"].append(cid)
    pending=list(requests.values())
    return {"criteria": results,"requests":pending,"work":work_counts(results,pending)}


def work_counts(results, pending):
    """Count distinct scoped tasks. Preserve patient, trial version and episode in the request IDs."""
    human={"study_team","investigator","patient","protocol_review","identify_subject"}
    return {"evidence_backed_decisions":sum(v["state"] in {"MET","NOT_MET"} and bool(v["evidence"])
                                              for v in results.values()),
            "human_questions":len({q["id"] for q in pending if q["route"] in human}),
            "record_lookups":len({q["id"] for q in pending if q["route"]=="retrieve_record"}),
            "engineering_items":len({q["id"] for q in pending if q["route"]=="engineering"})}


if __name__ == "__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ("rules","packet","study","version"):
        ap.add_argument("--"+key,required=True)
    args=ap.parse_args()
    print(json.dumps(screen(json.loads(Path(args.rules).read_text()),json.loads(Path(args.packet).read_text()),
                            args.study,args.version),indent=2))
