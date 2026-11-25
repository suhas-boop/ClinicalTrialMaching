"""Look for missed Boolean conclusions with source-backed operands held fixed.

Witnesses are hypothetical contract values. This diagnostic never creates or scores a patient chart.
"""
import argparse
from collections import Counter
from itertools import product
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "criterion_workbench"))
from evidence_review import evaluate


class Assignment:
    def __init__(self, values):
        self.values = values

    def read(self, spec):
        value = self.values[spec["label"]]
        if value is None:
            return None, "MISSING_DATA", [], "No alternate reporting form"
        return value, None, [], "Hypothetical operand"


def cutoffs(node, name):
    if not isinstance(node, dict):
        return []
    if node.get("fact") == name:
        return [node["value"]] if "value" in node else []
    result = []
    for child in node.values():
        for item in child if isinstance(child, list) else [child]:
            if isinstance(item, dict):
                result.extend(cutoffs(item,name))
    return result


def numeric_values(rule, name):
    cuts = sorted(set(cutoffs(rule["expression"],name) + cutoffs(rule.get("applies"),name)))
    if not cuts:
        raise ValueError(f"Missing comparator for numeric contract {name}")
    # Each open interval and exact threshold has one representative for this comparison.
    first = max(0, cuts[0] - 1)
    return sorted({first, *cuts, *(a + (b-a)/2 for a,b in zip(cuts,cuts[1:])), cuts[-1] + 1})


def check(row):
    rule = row["rule"]
    if row["subject"].startswith("Group/") or "hold" in rule["expression"]:
        return {"scope":"held before individual rule execution", "state":row["state"]}
    # Names bound to one contract must share the same value in every completion.
    known, domains = {}, {}
    for name, cid in row["bindings"].items():
        fact = row["decision"]["facts"].get(name,{})
        if fact.get("state") == "AVAILABLE":
            if cid in known and known[cid] != fact["value"]:
                raise ValueError("Conflicting values of a shared contract")
            known[cid] = fact["value"]
        elif rule["facts"][name]["kind"] == "bool":
            domains[cid] = [False,True]
        else:
            domains.setdefault(cid,[]).extend(numeric_values(rule,name))
    for cid in known:
        domains.pop(cid,None)
    # The released same_measurement family accepts either unit. For a missing
    # concentration supply one form at a time, avoiding inconsistent invented unit pairs.
    for name, cid in row["bindings"].items():
        if name == "serum_creatinine_umol_l" and "serum_creatinine_mg_dl" in row["bindings"] and cid in domains:
            domains[cid] = [None]
    witnesses = {}
    for vals in product(*domains.values()):
        completion = dict(zip(domains,vals))
        binding = known | completion
        mapping = {rule["facts"][name]["label"]:binding[cid] for name,cid in row["bindings"].items()}
        state = evaluate(rule,Assignment(mapping))["state"]
        witnesses.setdefault(state,{k:mapping[rule["facts"][k]["label"]] for k,cid in row["bindings"].items() if cid in domains})
        if len(witnesses) >= 2:
            break
    return {"scope":"hypothetical rule operands only","observed_state":row["state"],
            "two_distinct_witnesses":len(witnesses)>=2,"witnesses":witnesses}


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions",type=Path)
    parser.add_argument("out",type=Path)
    args=parser.parse_args()
    result={r["case"]:check(r) for r in json.loads(args.predictions.read_bytes()) if r["state"] not in {"MET","NOT_MET"}}
    counts=Counter("routing_or_protocol_hold" if "witnesses" not in d else
                   "different_completions" if d["two_distinct_witnesses"] else "possible_invariant" for d in result.values())
    with args.out.open("x") as f:json.dump({"counts":counts,"cases":result},f,indent=2)
    print(dict(counts))
