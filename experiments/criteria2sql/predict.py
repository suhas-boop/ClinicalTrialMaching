"""Build a blind development rule and freeze local normalized and FHIR predictions."""
import argparse
import hashlib
import json
import shlex
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from author import normalized


HERE = Path(__file__).resolve().parent
AUTHOR = HERE / "author"
ROOT = HERE.parents[1]
AUTHOR_INPUTS = (
    "published-context.json", "packet.json", "candidate.json", "review.json",
    "replay_judgments.py", "normalized.py", "concept-map.json", "controls/flat.json",
    "controls/chart.json",
)
RUNTIME_INPUTS = (
    "pocketmd.py", "criterion_workbench/rules.py", "criterion_workbench/text_author.py",
    "criterion_workbench/bounded_rules.py", "criterion_workbench/compiler.py",
    "criterion_workbench/runtime/catalog.json", "criterion_workbench/runtime/screen.py",
    "criterion_workbench/runtime/evidence.py",
)


def read(path):
    return json.loads(path.read_bytes())


def write(path, document):
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def public_cli(*args, cwd):
    command = [sys.executable, "-B", ROOT / "pocketmd.py", "author", *args]
    call = subprocess.run(command, cwd=cwd, check=False, capture_output=True, text=True)
    if call.returncode:
        raise RuntimeError(f"pocketmd.py author {args[0]} failed: {call.stderr.strip()} {call.stdout.strip()}")
    return json.loads(call.stdout)


def bundle_for(chart, study):
    patient_id = chart["patient_id"]
    visit = "screen-" + patient_id
    source = f"urn:pocketmd:criteria2sql:synthetic-controls-v1:chart:{chart['id']}"
    meta = {"versionId": "1", "lastUpdated": chart["screening_start"], "source": source}
    patient = {"resourceType": "Patient", "id": patient_id, "meta": meta}
    if chart["birth_date"] is not None:
        patient["birthDate"] = chart["birth_date"]
    encounter = {
        "resourceType": "Encounter", "id": visit, "meta": meta, "status": "in-progress",
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"},
        "subject": {"reference": f"Patient/{patient_id}"},
        "identifier": [{"system": "urn:pocketmd:demo:screening-study", "value": study}],
        "period": {"start": chart["screening_start"]},
    }
    entries = [
        {"fullUrl": f"https://example.org/fhir/{item['resourceType']}/{item['id']}", "resource": item}
        for item in (patient, encounter)
    ]
    return {"resourceType": "Bundle", "type": "collection", "entry": entries}, visit


def validate_controls(flat, charts):
    def identities(rows):
        ids = [row["id"] for row in rows]
        patients = [row["patient_id"] for row in rows]
        if any(type(value) is not int for value in ids) or len(ids) != len(set(ids)):
            raise ValueError("Expected a unique integer id per patient")
        if len(patients) != len(set(patients)):
            raise ValueError("A logical FHIR patient ID is used more than once")
        return {(row["id"], row["patient_id"], row["scope"]) for row in rows}

    if not flat or identities(flat) != identities(charts):
        raise ValueError("Normalized and clinical chart control identities differ")
    for rows, field in ((flat, "age"), (charts, "birth_date")):
        for row in rows:
            expected = "missing" if row[field] is None else "complete"
            if row["scope"] != expected:
                raise ValueError(f"Control scope differs from presence of {field}")


def run(out, scratch):
    out.mkdir()
    (out / "bundles").mkdir()
    packet = read(AUTHOR / "packet.json")
    sources, catalog = packet["sources"], packet["catalog"]
    concept = read(AUTHOR / "concept-map.json")
    scope = concept["scope"]
    published = read(AUTHOR / "published-context.json")
    if sources["criterion"] != published["criterion"] or concept["source"]["line"] != published["dev_line"]:
        raise ValueError("Author packet differs from the blind source locator or criterion")
    if concept["binding"]["selected_catalog_sha256"] != catalog["sha256"]:
        raise ValueError("The declared mapping and selected author catalog differ")
    workspace = ["--study", scope["study"], "--version", scope["version"], "--id", scope["criterion_id"],
                 "--work", scratch / "rule-store"]
    adapter = shlex.join([sys.executable, "-B", str(AUTHOR / "replay_judgments.py")])
    built = public_cli("build", *workspace, "--criterion", sources["criterion"], "--context",
                       sources["protocol"], "--facts", *catalog["facts"], "--model-command", adapter, cwd=scratch)
    if built["status"] != "EXECUTABLE":
        raise ValueError(f"Authoring did not yield an executable rule: {built}")
    public_cli("export", *workspace, "--out", out / "rule.json", cwd=scratch)
    rule = read(out / "rule.json")
    if rule["sha256"] != built["rule_sha256"] or rule["sources"] != sources or rule["catalog"] != catalog:
        raise ValueError("Exported rule differs from the reviewed packet or build")

    flat, charts = (read(AUTHOR / "controls" / name) for name in ("flat.json", "chart.json"))
    validate_controls(flat, charts)
    normalized_rows, fhir_rows = [], []
    for row in flat:
        identity = {key: row[key] for key in ("id", "patient_id", "scope")}
        ref = f"urn:pocketmd:criteria2sql:synthetic-controls-v1:flat:{row['id']}"
        result = normalized.screen(rule, row, ref)
        normalized_rows.append({**identity, **result})
    for chart in charts:
        identity = {key: chart[key] for key in ("id", "patient_id", "scope")}
        bundle, visit = bundle_for(chart, scope["study"])
        subject = chart["patient_id"]
        path = out / "bundles" / f"{subject}.json"
        write(path, bundle)
        result = public_cli("screen", "--study", scope["study"], "--version", scope["version"],
                            "--id", scope["criterion_id"], "--rule", out / "rule.json",
                            "--expected-sha256", rule["sha256"], "--bundle", path,
                            "--patient", subject, "--encounter", visit, "--as-of", chart["as_of"], cwd=scratch)
        result["criterion_id"] = result.pop("id")
        if result["criterion_id"] != scope["criterion_id"] or result["patient"] != subject:
            raise ValueError("FHIR screening returned a different patient or criterion")
        fhir_rows.append({**identity, **result})
    write(out / "normalized.json", normalized_rows)
    write(out / "fhir.json", fhir_rows)
    inputs = [Path(__file__).resolve(), *(AUTHOR / name for name in AUTHOR_INPUTS),
              *(ROOT / name for name in RUNTIME_INPUTS)]
    manifests = {
        "format": "criteria2sql-blind-prediction-freeze-v1", "scope": scope,
        "rule_sha256": rule["sha256"],
        "inputs_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs},
        "outputs_sha256": {str(path.relative_to(out)): digest(path) for path in sorted(out.rglob("*.json"))},
        "counts": {
            name: {scope: dict(Counter(row["state"] for row in rows if row["scope"] == scope))
                   for scope in ("complete", "missing")}
            for name, rows in (("normalized", normalized_rows), ("fhir", fhir_rows))
        },
    }
    write(out / "freeze.json", manifests)
    return manifests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="New prediction directory")
    parser.add_argument("--verify-against", type=Path, help="Compare with a prior frozen prediction directory")
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists():
        parser.error("Choose a fresh output directory")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent) as temp:
        scratch = Path(temp)
        staging = scratch / "predictions"
        manifest = run(staging, scratch)
        if args.verify_against:
            previous = args.verify_against.resolve()
            if manifest != read(previous / "freeze.json"):
                raise ValueError("Replay differs from the previously frozen manifest")
            for name, expected in manifest["outputs_sha256"].items():
                if digest(previous / name) != expected:
                    raise ValueError(f"The previously frozen file has changed: {name}")
        # Reserve the destination exclusively, then publish the complete directory atomically.
        out.mkdir()
        staging.replace(out)
    print(json.dumps({"out": str(out), "freeze_sha256": digest(out / "freeze.json"),
                      "rule_sha256": manifest["rule_sha256"], "counts": manifest["counts"]}, indent=2))


if __name__ == "__main__":
    main()
