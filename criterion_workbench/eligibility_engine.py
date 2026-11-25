"""Typed rule evaluation for active PocketMD development. Base operations come from the frozen release."""
import math
from bindings import fold, result, Snapshot
from rules_engine import typed, OPS, ROLES
from measurement_families import FAMILIES


def validate(rule):
    facts = rule["facts"]
    used_families = set()
    for key, spec in facts.items():
        if not key or not spec.get("label") or not spec.get("scope") or spec.get("role") not in ROLES:
            raise ValueError(f"Incomplete evidence definition {key}")
        kind = spec["kind"]
        if kind not in ("bool","enum","number") or (kind=="number" and not spec.get("unit")):
            raise ValueError(f"Invalid type or unit for {key}")
        if kind=="enum" and (not spec.get("values") or len(set(spec["values"]))!=len(spec["values"])):
            raise ValueError(f"Invalid enumeration {key}")

    def check(node):
        if type(node) is bool:
            return
        if not isinstance(node,dict):
            raise ValueError(f"Invalid node {node!r}")
        keys=set(node)
        if keys == {"same_measurement","family"}:
            family_id=node["family"]
            if not isinstance(family_id,str) or family_id not in FAMILIES:
                raise ValueError("Unknown clinical measurement family")
            approved=FAMILIES[family_id]["forms"]
            forms=node["same_measurement"]
            if not isinstance(forms,list) or len(forms)!=len(approved):
                raise ValueError("Provide all distinct reporting forms approved for the measurement")
            seen=set()
            comparators=set()
            for form in forms:
                if not isinstance(form,dict) or set(form)!={"fact","op","value"} or form["op"] not in {"gt","ge","lt","le","eq","ne"}:
                    raise ValueError("Each reporting form must be a numeric threshold comparison")
                key=form["fact"]
                if not isinstance(key,str) or key not in approved or key in seen or facts.get(key)!=approved[key]["contract_spec"]:
                    raise ValueError("Unexpected reporting form or clinical scope for "+family_id)
                check(form)
                seen.add(key)
                comparators.add(form["op"])
            used_families.add(family_id)
            if len(comparators)!=1:
                raise ValueError("Reporting forms disagree on the comparison operator")
        elif keys in ({"all"},{"any"}):
            members=next(iter(node.values()))
            if not isinstance(members,list) or not members:
                raise ValueError("Empty Boolean group")
            for member in members:
                check(member)
        elif keys=={"if","then","else"} or keys=={"not"}:
            for member in node.values():
                check(member)
        elif keys=={"hold"} and isinstance(node["hold"],str) and node["hold"].strip():
            return
        elif keys in ({"fact"},{"fact","op","value"}):
            spec=facts[node["fact"]]
            if keys=={"fact"}:
                if spec["kind"]!="bool":
                    raise ValueError(f"Comparison required for {node}")
                return
            op=node["op"]
            val=node["value"]
            if op not in OPS or (op in {"lt","le","gt","ge"} and spec["kind"]!="number"):
                raise ValueError(f"Unsupported comparator {node}")
            values=val if op=="in" else [val]
            if not isinstance(values,list) or not values or not all(typed(v,spec) for v in values):
                raise ValueError(f"Invalid operands {node}")
        else:
            raise ValueError(f"Unexpected node {node}")
    check(rule["expression"])
    if "applies" in rule:
        check(rule["applies"])
    return used_families


def evaluate(rule,snapshot):
    trace={}
    def visit(node):
        if type(node) is bool:
            return result("MET" if node else "NOT_MET","Protocol branch resolved.")
        if "fact" in node:
            k=node["fact"]
            spec=rule["facts"][k]
            if k not in trace:
                trace[k]=snapshot.read(spec)
            value, issue, refs, why=trace[k]
            if issue:
                return result(issue,why,refs)
            op=node.get("op","eq")
            target=node.get("value",True)
            passed=OPS[op](value,target)
            return result("MET" if passed else "NOT_MET",f"{spec['label']} = {value} (requires {op} {target}).",refs)
        if "same_measurement" in node:
            request=FAMILIES[node["family"]]["request"]
            observations = [visit(form) for form in node["same_measurement"]]
            usable = [item for item in observations if item["state"] in {"MET","NOT_MET"}]
            # A missing unit is fine. An unresolved binding or conflicting results
            # for a reported unit must not be masked by the other reporting form.
            for item in observations:
                if item["state"] not in {"MET","NOT_MET","MISSING_DATA"}:
                    return item
                if item["state"] == "MISSING_DATA" and item["evidence"]:
                    return item
            if not usable:
                return result("MISSING_DATA","Obtain "+request+".")
            refs = [ref for item in usable for ref in item["evidence"]]
            if len({item["state"] for item in usable}) != 1:
                return result("MISSING_DATA","Reconcile "+request+" across reporting forms.",refs)
            return result(usable[0]["state"]," ".join(item["reason"] for item in usable),refs)
        if "hold" in node:
            return result("AUTHORING_HOLD",node["hold"])
        if "not" in node:
            child=visit(node["not"])
            state={"MET":"NOT_MET","NOT_MET":"MET"}.get(child["state"],child["state"])
            return result(state,"Negated protocol condition. "+child["reason"],child["evidence"])
        if "if" in node:
            condition=visit(node["if"])
            if condition["state"] not in {"MET","NOT_MET"}:
                return condition
            selected=visit(node["then"] if condition["state"]=="MET" else node["else"])
            return result(selected["state"],selected["reason"],condition["evidence"]+selected["evidence"])
        key="all" if "all" in node else "any"
        return fold([visit(child) for child in node[key]],key=="all")
    gate=visit(rule["applies"]) if "applies" in rule else None
    if gate and gate["state"]=="NOT_MET":
        out=result("NOT_APPLICABLE","Outside the criterion's protocol-defined scope. "+gate["reason"],gate["evidence"])
    elif gate and gate["state"]!="MET":
        out=gate
    else:
        out=visit(rule["expression"])
        if gate:
            out["evidence"]=sorted(set(out["evidence"]+gate["evidence"]))
    out["facts"]={k:{"label":rule["facts"][k]["label"],"value":v,"state":s or "AVAILABLE","evidence":e}
                  for k,(v,s,e,_) in trace.items()}
    return out
