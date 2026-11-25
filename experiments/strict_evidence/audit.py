"""Join blind chart review to frozen FHIR extraction, contract reads and executed rule branches."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from xml.etree import ElementTree

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
BENCH = PROJECT / "nih_benchmark"
sys.path.insert(0, str(PROJECT/"criterion_workbench"))
from evidence_review import evaluate


def load(path):
    return json.loads(path.read_bytes())


def registry(source, case, studies):
    path = BENCH/"round17/registry/benchmark_2015/xml"/(source["trial_id"]+".xml")
    if not path.exists():
        return {"available": False, "assigned_text": source["criterion_text"]}
    text = " ".join((ElementTree.parse(path).findtext("eligibility/criteria/textblock") or "").split())
    clause = " ".join(source["criterion_text"].split())
    start = text.casefold().find(clause.casefold())
    headings = list(re.finditer(r"\b(inclusion|exclusion)\s+criteria\b", text[:start], re.I)) if start >= 0 else []
    study = studies[source["trial_id"]]
    join = next(item for item in study["criterion_joins"] if str(item["case"]) == case)
    return {"file":str(path.relative_to(PROJECT)), "sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
            "release_version_verified":study["benchmark_version_verified"],
            "release_criterion_join":join["status"],
            "element":"eligibility/criteria/textblock", "verbatim_after_whitespace_normalization":start >= 0,
            "heading_at_match":headings[-1][1].lower() if headings else None}


class FrozenReads:
    """Use the production evaluator to reconstruct subexpression states from frozen fact reads."""
    def __init__(self, row):
        self.reads = {key: row["decision"]["facts"][key] for key in row["decision"]["facts"]}
        self.specs = row["rule"]["facts"]

    def read(self, spec):
        name = next(k for k in self.reads if self.specs[k] == spec)
        result = self.reads[name]
        return (result["value"], None if result["state"] == "AVAILABLE" else result["state"],
                result["evidence"], result["state"])


def branches(row):
    if row["subject"].startswith("Group/"):
        return [{"path":"subject gate", "state":row["state"], "reason":row["decision"]["reason"]}]
    tree = row["rule"]["expression"]
    snapshot = FrozenReads(row)
    result = []
    def walk(node, path):
        verdict = evaluate({"expression":node,"facts":row["rule"]["facts"]}, snapshot)
        result.append({"path":path, "operator":next(k for k in node if k != "family"),
                       "state":verdict["state"], "evidence":verdict["evidence"]})
        for key in ("all","any","same_measurement"):
            for i, child in enumerate(node.get(key, [])):
                walk(child,f"{path}.{key}[{i}]")
        if "not" in node:
            walk(node["not"],path+".not")
    if "applies" in row["rule"]:
        walk(row["rule"]["applies"], "applies")
        gate = result[0]["state"]
        if gate != "MET":
            expected = "NOT_APPLICABLE" if gate == "NOT_MET" else gate
            if expected != row["state"]:
                raise ValueError(f"Scope gate differs from the frozen screen for {row['case']}")
            result.append({"path":"root", "state":"NOT_EXECUTED", "reason":"Applicability gate"})
            return result
    root_index = len(result)
    walk(tree,"root")
    if result[root_index]["state"] != row["state"]:
        raise ValueError(f"Branch reconstruction differs from the frozen screen for {row['case']}")
    return result


def audit(freeze):
    manifest = load(freeze/"freeze.json")
    for name, digest in manifest["outputs"].items():
        if hashlib.sha256((freeze/name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Freeze mismatch for {name}")
    pack = load(BENCH/"round11/compiled.json")
    if pack["sha256"] != manifest["catalog_sha256"]:
        raise ValueError("Catalog does not match screen")
    charts, rows = (load(freeze/name) for name in ("charts.json","predictions.json"))
    notes = load(BENCH/"round9/notes.json")
    studies = load(BENCH/"round17/registry/benchmark_2015/manifest.json")["studies"]
    review = [row for name in ("early","middle","late") for row in load(HERE/"reviews"/(name+".json"))]
    assessments = {r["case"]:r for r in review}
    if len(assessments) != len(review) or set(assessments) != {r["case"] for r in rows}:
        raise ValueError("Expected exactly one source review per assignment")
    records = []
    for row in rows:
        case, subject = row["case"], row["subject"]
        reviewed = assessments[case]
        exact = notes[subject.split("/")[1]].splitlines()
        selected = reviewed["lines"]
        if not selected or any(type(i) is not int or not 0 <= i < len(exact) for i in selected):
            raise ValueError(f"Unlocated note passage for {case}")
        chart = charts[subject]
        related = {ref:{"lines":r["lines"], "concept":r["resource"].get("code",
                   r["resource"].get("medicationCodeableConcept",{})).get("text"),
                   "value":{k:v for k,v in r["resource"].items() if k.startswith("value")}}
                   for ref,r in chart.items() if set(r["lines"]).intersection(selected)}
        reads = {}
        for name,cid in row["bindings"].items():
            contract = pack["contracts"][cid]
            reads[name] = {"contract":cid,"spec":contract["spec"],"selectors":contract["native"],
                           "read":row["decision"]["facts"].get(name, {"state":"NOT_EXECUTED"}),
                           "source_lines":{ref:chart[ref]["lines"] for ref in
                                row["decision"]["facts"].get(name,{}).get("evidence",[]) if ref in chart}}
        records.append({"case":case,"study":row["study"],"subject":subject,"state":row["state"],
            "assigned_clause":row["source"]["criterion_text"],"assigned_polarity":row["source"]["criterion_type"],
            "registry":registry(row["source"],case,studies), "source_sha256":row["source_sha256"],
            "closest_note_passages":[{"line":i,"text":exact[i],"source_role":
                "benchmark_assumption" if "will comply with the trial protocol without any practical issues" in exact[i]
                else "original narrative"} for i in selected],
            "baseline_blocker_class":reviewed["classification"],"baseline_source_review":reviewed["blocker"],
            "fhir_from_these_lines":related,"bindings":reads,"expression":row["rule"]["expression"],
            "branches":branches(row),"reason":row["decision"]["reason"],"next_requests":row["requests"]})
    return records


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("freeze", type=Path)
    p.add_argument("out", type=Path)
    a = p.parse_args()
    records = audit(a.freeze)
    with a.out.open("x") as f:
        json.dump(records,f,ensure_ascii=False,indent=2)
        f.write("\n")
    print(len(records), a.out)
