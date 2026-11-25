"""Retrieve normalized chart evidence from a local FHIR collection and rescreen."""
import argparse
from collections import defaultdict
import json
from pathlib import Path

from evidence_review import DECIDED, screen
from bindings import FACTS, Snapshot, contract, instant, ref


def enrich_packet(rules, packet, archive, study, version):
    """Archive is a trusted export. It cannot supply mapping grants, roles or rule context."""
    if archive.get("resourceType") != "Bundle" or archive.get("type") != "collection":
        raise ValueError("Chart archive must be a FHIR collection Bundle.")
    ctx = packet["context"]
    snapshot = Snapshot(packet["bundle"], ctx, study, version)
    needed = snapshot.enabled & {contract(f) for rule in rules.values() for f in rule["facts"].values()}
    groups = defaultdict(list)
    for entry in archive.get("entry", []):
        r = entry["resource"]
        if r.get("resourceType") in {"Observation", "DocumentReference"}:
            if instant(r["meta"]["lastUpdated"]) <= snapshot.at:
                groups[(r["resourceType"], r["id"])].append(r)

    def scoped(r):
        return (r.get("resourceType") == "Observation"
                and r.get("subject", {}).get("reference") == snapshot.patient
                and r.get("encounter", {}).get("reference") == snapshot.encounter
                and [f.get("reference") for f in r.get("focus", [])] == [snapshot.episode]
                and any(c.get("system") == FACTS and c.get("version") == version and c.get("code") in needed
                        for c in r.get("code", {}).get("coding", [])))

    # Follow every visible version of each selected logical ID so amendments and
    # withdrawals are evaluated by the same as-of reducer as the original chart.
    selected = {("Observation", r["id"]) for r in snapshot.exact.values() if scoped(r)}
    selected.update(k for k, history in groups.items() if any(scoped(r) for r in history))
    sources = set()
    for key in selected:
        original = [r for r in snapshot.exact.values() if (r["resourceType"], r["id"]) == key]
        for r in original + groups.get(key, []):
            for link in r.get("derivedFrom", []):
                parts = link.get("reference", "").split("/")
                if len(parts) == 4 and parts[0] == "DocumentReference" and parts[2] == "_history":
                    sources.add((parts[0], parts[1]))

    additions = {}
    for key in sorted(selected | sources):
        for r in groups.get(key, []):
            if r.get("subject", {}).get("reference") != snapshot.patient:
                raise ValueError("A linked resource's patient identity changed. Reconcile the archive.")
            identifier = ref(r)
            existing = snapshot.exact.get(identifier, additions.get(identifier))
            if existing is not None and existing != r:
                raise ValueError("Conflicting copies of a chart resource version.")
            if existing is None:
                additions[identifier] = r
    entries = packet["bundle"]["entry"] + [{"resource": r} for _, r in sorted(additions.items())]
    enriched = {**packet, "bundle": {**packet["bundle"], "entry": entries}}
    return enriched, sorted(additions)


def recover(rules, packet, archive, study, version):
    before = screen(rules, packet, study, version)
    enriched, additions = enrich_packet(rules, packet, archive, study, version)
    after = screen(rules, enriched, study, version)
    transitions = {k: {"before": before["criteria"][k]["state"], "after": v["state"],
                       "evidence": v["evidence"]} for k, v in after["criteria"].items()}
    newly_decided = [k for k, v in transitions.items() if v["before"] not in DECIDED
                     and v["after"] in {"MET", "NOT_MET"} and v["evidence"]]
    return {"transitions": transitions, "new_evidence_backed_decisions": newly_decided,
            "new_resource_versions": sorted(additions), "remaining_requests": after["requests"],
            "criteria": after["criteria"]}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for field in ("rules", "packet", "archive", "study", "version"):
        p.add_argument("--" + field, required=True)
    args = p.parse_args()
    def read(path):
        return json.loads(Path(path).read_text())
    print(json.dumps(recover(read(args.rules), read(args.packet), read(args.archive),
                             args.study, args.version), indent=2))
