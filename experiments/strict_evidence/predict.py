"""Freeze strict TrialGPT predictions from original notes using the normal FHIR screener."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
DEFAULT_PROJECT = HERE.parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n")


def chart_index(resources):
    index = {}
    source_lines = {}
    for r in resources:
        kind = r["resourceType"]
        if kind == "Provenance":
            for entity in r["entity"]:
                for ext in entity.get("extension", []):
                    if ext["url"] == "urn:pocketmd:trialgpt:source-sentence":
                        for target in r["target"]:
                            source_lines.setdefault(target["reference"], []).append(ext["valueInteger"])
        if kind in {"DocumentReference", "Device", "Provenance", "Patient", "Group"}:
            continue
        ref = f"{kind}/{r['id']}"
        index[ref] = r
    return {ref: {"resource": r, "lines": sorted(set(source_lines.get(ref, [])))} for ref,r in index.items()}


def run(project, directory, cli_check):
    # The source iterator rebuilds original benchmark charts and verifies note identity.
    # Only the strict screen is invoked. Optional cohort/term/clarification arms are unused.
    import subprocess
    bench = project / "nih_benchmark"
    sys.path.insert(0, str(bench / "round16"))
    from literal_scope import frozen_assignments, read_json, screen, verify, R11
    pack = verify(read_json(R11 / "compiled.json"))
    rows = []
    charts = {}
    checked = 0
    notes = read_json(bench / "round9" / "notes.json")
    with tempfile.TemporaryDirectory() as scratch:
        tmp = Path(scratch)
        for a, subject, resources, approved in frozen_assignments():
            case = str(a["annotation_id"])
            if subject not in charts:
                charts[subject] = chart_index(resources)
                if cli_check:
                    filename = tmp / (a["patient"] + ".json")
                    write(filename, {"resourceType":"Bundle", "type":"collection",
                                     "entry":[{"resource":r} for r in resources]})
            trace = screen(resources, subject, pack, a["study"], case)
            if cli_check:
                args = [sys.executable, "-B", str(project/"pocketmd.py"), "fhir-screen",
                        "--bundle", str(tmp/(a["patient"] + ".json")), "--subject", subject,
                        "--study", a["study"], "--criterion", case]
                actual = json.loads(subprocess.check_output(args))
                if actual != trace:
                    raise ValueError(f"CLI trace differs for {case}")
                checked += 1
            if trace["source_sha256"] != approved[subject]:
                raise ValueError(f"Unverified source for {case}")
            result = trace["criteria"][case]
            lines = notes[a["patient"]].splitlines()
            if result["state"] in {"MET", "NOT_MET"} and not (result["evidence"] and result["source_sentences"]):
                raise ValueError(f"Missing decisive evidence for {case}")
            entry = pack["rules"][case]
            rows.append({"case":case,"study":a["study"],"subject":subject,"source_sha256":approved[subject],
                         "source":entry["source"], "rule":entry["rule"], "bindings":entry["bindings"],
                         "state":result["state"], "decision":result, "requests":trace["requests"],
                         "cited_lines":[{"line":i, "text":lines[i]} for i in result["source_sentences"]]})
    if len(rows) != 134 or len(set(r["case"] for r in rows)) != 134 or len(charts) != 44:
        raise ValueError("Assignment or subject population changed")
    write(directory/"predictions.json", rows)
    write(directory/"charts.json", charts)
    code = set()
    for m in sys.modules.copy().values():
        if filename := getattr(m, "__file__", None):
            p = Path(filename).resolve()
            if p.is_relative_to(project) and p.suffix == ".py" and p.exists():
                code.add(p)
    for pattern in ("round9/notes.json", "round9/assignments.json", "round9/note_hashes.json",
                    "round9/export/cases.json", "round9/source_review.psv", "round9/icd10cm.json",
                    "round9/rxnorm.json", "round11/compiled.json"):
        code.add(bench/pattern)
    manifest = {"assignments":len(rows), "subjects":len(charts),"catalog_sha256":pack["sha256"],
                "cli_trace_comparisons":checked,"driver_sha256":digest(Path(__file__)),
                "inputs":{str(p.relative_to(project)):digest(p) for p in sorted(code)},
                "outputs":{name:digest(directory/name) for name in ("predictions.json","charts.json")}}
    write(directory/"freeze.json",manifest)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("out", type=Path)
    p.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    p.add_argument("--cli-check", action="store_true", help="Compare every trace with pocketmd.py fhir-screen")
    args = p.parse_args()
    dest = args.out.resolve()
    if dest.exists():
        p.error("Choose a new output path")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as work:
        staging = Path(work)/"freeze"
        staging.mkdir()
        run(args.project.resolve(), staging, args.cli_check)
        dest.mkdir()
        staging.replace(dest)
    print(digest(dest/"freeze.json"), dest/"freeze.json")
