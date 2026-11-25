"""Score the frozen synthetic controls against one Criteria2SQL development annotation."""
import argparse
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path

from evidence import inspect_evidence
from verify_source import DEV_LINE, FILES, REVISION, SCHEMA_LINE

HERE = Path(__file__).resolve().parent
EXPERIMENT = HERE.parent
PROJECT = EXPERIMENT.parents[1]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_bytes())


def by_patient(records):
    indexed = {row["patient_id"]: row for row in records}
    if len(indexed) != len(records):
        raise ValueError("Duplicate patient identifiers")
    return indexed


def summarize(cases, channel):
    mismatches = [r for r in cases if r[channel] != r["sql_state"]]
    return {
        "complete": len(cases), "agreements": len(cases) - len(mismatches),
        "false_definitives": sum(r[channel] in {"MET", "NOT_MET"} for r in mismatches),
        "false_met": sum(r[channel] == "MET" for r in mismatches),
        "false_not_met": sum(r[channel] == "NOT_MET" for r in mismatches),
        "abstentions": sum(r[channel] not in {"MET", "NOT_MET"} for r in cases),
        "mismatch_patient_ids": [r["patient_id"] for r in mismatches],
        "selected_patient_ids": [r["patient_id"] for r in cases if r[channel] == "MET"],
    }


FREEZE_SHA256 = "16ef10ce67c4504f71b8630b265bd29ba165f1ff9b7732321ef3c80a11c5a52a"
ANNOTATION_SHA256 = "df22eee4a9d440cd46a8ff385753d0640c319a6d6a5e644c5f3d5b75dcd69756"
SCHEMA_SHA256 = "e6890b111511bb7c87815220088136abecd3e10d99ddb234a7128d5eb075c906"


def verified_freeze(folder):
    if sha256(folder / "freeze.json") != FREEZE_SHA256:
        raise ValueError("The manifest differs from the recorded pre-scoring freeze")
    manifest = load(folder / "freeze.json")
    for base, entries in ((PROJECT, manifest["inputs_sha256"]), (folder, manifest["outputs_sha256"])):
        for name, expected in entries.items():
            if sha256(base / name) != expected:
                raise ValueError(f"Freeze hash mismatch: {name}")
    rule = load(folder / "rule.json")
    body = {k: v for k, v in rule.items() if k != "sha256"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    if not (rule["sha256"] == manifest["rule_sha256"] == hashlib.sha256(canonical.encode()).hexdigest()):
        raise ValueError("Exported rule identity differs from prediction freeze")
    return manifest, rule


def execute_sql(annotation, schema, complete):
    # Source types and order are preserved. Only id and age are needed by this query.
    headers = schema["header"]
    types = {"int": "INTEGER", "float": "REAL", "string": "TEXT"}
    columns = [f'"{name}" {types[kind]}' for name, kind in zip(headers, schema["types"])]
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE records (" + ", ".join(columns) + ")")
        db.executemany("INSERT INTO records (id, age) VALUES (?, ?)", [(r["id"], r["age"]) for r in complete])
        sql_ids = sorted(record[0] for record in db.execute(annotation["query"]))
        structured = annotation["sql"]
        if structured["agg"] != 0 or headers[structured["sel"]] != "id" or len(structured["conds"]) != 1:
            raise ValueError("The selected release annotation requires another structured representation")
        column, op, parameter = structured["conds"][0]
        operators = ("=", ">", "<", ">=", "<=", "<>")
        decoded = f'SELECT "{headers[structured["sel"]]}" FROM records WHERE "{headers[column]}" {operators[op]} ?'
        decoded_ids = sorted(result[0] for result in db.execute(decoded, (parameter,)))
    return {"published_query": annotation["query"], "published_selected_ids": sql_ids,
            "structured_query": decoded, "structured_parameter": parameter, "structured_selected_ids": decoded_ids,
            "representations_agree": sql_ids == decoded_ids}


def score(folder):
    manifest, rule = verified_freeze(folder)
    if sha256(HERE / "reference.jsonl") != ANNOTATION_SHA256 or sha256(HERE / "schema.json") != SCHEMA_SHA256:
        raise ValueError("The evaluator annotation or schema differs from the verified source")
    ann, schema = load(HERE / "reference.jsonl"), load(HERE / "schema.json")
    if rule["sources"]["criterion"] != ann["question"] or ann["table_id"] != schema["id"]:
        raise ValueError("Reference and rule refer to different source text or schema")
    controls = EXPERIMENT / "author" / "controls"
    flat, charts = [by_patient(load(controls / name)) for name in ("flat.json", "chart.json")]
    norm, fhir = [by_patient(load(folder / name)) for name in ("normalized.json", "fhir.json")]
    if not (flat.keys() == charts.keys() == norm.keys() == fhir.keys()):
        raise ValueError("Patient sets differ across inputs and outputs")
    sql = execute_sql(ann, schema, [r for r in flat.values() if r["scope"] == "complete"])
    selected = set(sql["published_selected_ids"])
    complete, missing = [], []
    for pid, row in flat.items():
        for prediction in (norm[pid], fhir[pid]):
            if (prediction["id"], prediction["scope"], prediction["rule_sha256"]) != (row["id"], row["scope"], rule["sha256"]):
                raise ValueError(f"Prediction identity mismatch for {pid}")
        expected_ref = f"urn:pocketmd:criteria2sql:synthetic-controls-v1:flat:{row['id']}/age"
        if norm[pid]["evidence"] != [expected_ref]:
            raise ValueError(f"Normalized decision evidence differs from its designated input for {pid}")
        audit = inspect_evidence(row, charts[pid], load(folder / "bundles" / (pid + ".json")), fhir[pid])
        case = {**row, "normalized": norm[pid]["state"], "fhir": fhir[pid]["state"],
                "normalized_evidence": norm[pid]["evidence"], "fhir_reason": fhir[pid]["reason"], "evidence_audit": audit}
        if row["scope"] == "complete":
            case["sql_state"] = "MET" if row["id"] in selected else "NOT_MET"
            complete.append(case)
        elif row["scope"] == "missing":
            missing.append(case)
        else:
            raise ValueError(f"Unknown evidence scope for {pid}")
    return {
        "revision": REVISION, "split": "dev", "annotation_line": DEV_LINE, "schema_line": SCHEMA_LINE,
        "source_sha256": {name: hashes[0] for name, hashes in FILES.items()},
        "annotation_sha256": ANNOTATION_SHA256, "schema_sha256": SCHEMA_SHA256,
        "freeze_sha256": FREEZE_SHA256, "rule_sha256": rule["sha256"],
        "predictions_sha256": {n: manifest["outputs_sha256"][n] for n in ("normalized.json", "fhir.json")},
        "evaluator_sha256": {n: sha256(HERE / n) for n in ("score.py", "evidence.py", "verify_source.py")},
        "sqlite_version": sqlite3.sqlite_version, "criterion": ann["question"], "released_sql": sql,
        "complete_cases": complete, "complete_summary": {k: summarize(complete, k) for k in ("normalized", "fhir")},
        "missing_cases": missing,
        "missing_summary": {"denominator": len(missing), "excluded_from_sql": len(missing),
                            "both_abstained": sum(r["fhir"] == r["normalized"] == "MISSING_DATA" for r in missing)},
        "complete_decisions_with_source_references": sum(r["evidence_audit"]["source_references_in_decision"] for r in complete),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="A new output directory")
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Output directory exists; choose a new directory")
    document = json.dumps(score(args.freeze.resolve()), indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.out.parent) as temporary:
        staging = Path(temporary) / "score"
        staging.mkdir()
        (staging / "score.json").write_text(document)
        args.out.mkdir(exist_ok=False)
        staging.replace(args.out)
    print(args.out / "score.json")
