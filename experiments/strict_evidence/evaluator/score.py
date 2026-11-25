"""Verify paired strict prediction freezes before joining the published evaluation labels."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import tempfile


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
BENCHMARK = PROJECT / "nih_benchmark"
BASELINE = "88d1fd3fe4b48699b9a00c55aa64394a97657503db92b464f3308b2f6b485627"
PRIOR = "f0eb605ec1998262c2b2d6071b8e866a46bd744788abcff076255aab6de21d1a"
PUBLISHER = "14c547184fac9b013cd17441fd028845b40150c76b022e58334f5494077e5234"
NOTES = "25f9b95d633c111c607e7a552f36af337d7de949d21c610310391cb2f0b3fc66"
BLIND_ASSIGNMENTS = "7f208d1476911716d9ceef00162f5ac94bd6b5719d01678492daf78f631519a3"
DEFINITE = {"MET", "NOT_MET"}
LABELS = {"included": "MET", "not excluded": "MET", "not included": "NOT_MET", "excluded": "NOT_MET",
          "not enough information": "MISSING_DATA", "not applicable": "NOT_APPLICABLE"}


def checked(path, expected):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"Checksum differs from freeze: {path}")
    return data


def canon(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def indexed(rows, key):
    index = {r[key]: r for r in rows}
    if len(index) != len(rows) or len(index) != 134:
        raise ValueError("Expected 134 unique annotation identifiers")
    return index


def predictions(folder, pin, notes):
    manifest = json.loads(checked(folder / "freeze.json", pin))
    if set(manifest["outputs"]) != {"predictions.json", "charts.json"}:
        raise ValueError("Forecast freeze must cover predictions and underlying evidence")
    rows = indexed(json.loads(checked(folder / "predictions.json", manifest["outputs"]["predictions.json"])), "case")
    charts = json.loads(checked(folder / "charts.json", manifest["outputs"]["charts.json"]))
    if manifest["assignments"] != 134 or manifest["subjects"] != 44 or set(charts) != {r["subject"] for r in rows.values()}:
        raise ValueError("Population or chart identity mismatch")
    for case, r in rows.items():
        note = notes[r["subject"].split("/", 1)[1]]
        source = note.splitlines()
        decision = r["decision"]
        if (r["state"] != decision["state"] or r["study"] != r["source"]["trial_id"] or
                hashlib.sha256(note.encode()).hexdigest() != r["source_sha256"]):
            raise ValueError(f"Decision scope or patient source mismatch in {case}")
        lines = decision.get("source_sentences", [])
        if r["cited_lines"] != [{"line": i, "text": source[i]} for i in lines] or any(i < 0 for i in lines):
            raise ValueError(f"Decision source lines differ from original note in {case}")
        refs = set(decision["evidence"])
        supporting = set()
        for ref in refs | set(decision.get("partial_evidence", [])):
            fact = charts[r["subject"]][ref]
            resource = fact["resource"]
            if ref != resource["resourceType"] + "/" + resource["id"] or resource["subject"]["reference"] != r["subject"]:
                raise ValueError(f"Clinical evidence reference or owner mismatch in {case}: {ref}")
            if any(i < 0 or i >= len(source) for i in fact["lines"]):
                raise ValueError(f"Invalid evidence provenance in {case}: {ref}")
            if ref in refs:
                supporting.update(fact["lines"])
        if r["state"] in DEFINITE and (not refs or not lines or set(lines) != supporting):
            raise ValueError(f"Definitive decision lacks chart-supported source lines in {case}")
    blind_rows = [[case, r["subject"].split("/", 1)[1], r["study"], r["source"]["criterion_type"],
                   r["source"]["criterion_text"], r["source_sha256"]]
                  for case, r in sorted(rows.items(), key=lambda pair: int(pair[0]))]
    if canon(blind_rows) != BLIND_ASSIGNMENTS:
        raise ValueError("Governing criteria or patient source pointers differ from the pinned publisher projection")
    return manifest, rows, charts


def strict_counts(rows, gold):
    counts = Counter()
    pending = Counter()
    for case, row in rows.items():
        outcome, reference = row["state"], gold[case]
        if reference in DEFINITE:
            counts["physician_definitive"] += 1
            if outcome == reference:
                counts["agree"] += 1
            elif outcome in DEFINITE:
                counts["opposite_definitive"] += 1
            else:
                pending[outcome] += 1
        elif outcome in DEFINITE:
            counts["definitive_on_indeterminate"] += 1
    return {"assignments": len(gold), "physician_definitive": counts["physician_definitive"],
            "physician_indeterminate": len(gold) - counts["physician_definitive"], "agree": counts["agree"],
            "opposite_definitive": counts["opposite_definitive"], "definitive_on_indeterminate": counts["definitive_on_indeterminate"],
            "total_unsupported_or_opposite_definitives": counts["opposite_definitive"] + counts["definitive_on_indeterminate"],
            "pending_physician_definitive": sum(pending.values()), "pending_by_state": dict(sorted(pending.items())),
            "all_assignment_abstentions": sum(r["state"] not in DEFINITE for r in rows.values())}


def adjudication(outcome, reference):
    if outcome not in DEFINITE:
        return "abstained"
    if reference not in DEFINITE:
        return "definitive_on_indeterminate"
    return "agree" if reference == outcome else "opposite_definitive"


def evaluate(base_dir, candidate_dir, candidate_pin):
    # Freeze checks and evidence/source validation finish before the reader opens any labels.
    notes = json.loads(checked(BENCHMARK / "round9/notes.json", NOTES))
    bm, old, old_charts = predictions(base_dir, BASELINE, notes)
    cm, new, charts = predictions(candidate_dir, candidate_pin, notes)
    if cm["cli_trace_comparisons"] != 134:
        raise ValueError("Candidate freeze lacks 134 command-line replication checks")
    prior = json.loads(checked(BENCHMARK / "reconcile/predictions_before_labels.json", PRIOR))
    released = indexed(prior["rows"], "annotation")
    if set(old) != set(new) or set(old) != set(released):
        raise ValueError("Assignment IDs differ between releases")
    changed = []
    for case in sorted(old, key=int):
        a, b, anchor = old[case], new[case], released[case]
        if (a["state"], a["study"], a["source_sha256"]) != (anchor["strict"], anchor["study"], anchor["public_note_sha256"]):
            raise ValueError(f"Baseline differs from released strict prediction for {case}")
        for k in ("subject", "study", "source_sha256"):
            if a[k] != b[k]:
                raise ValueError(f"Assignment drift in {case}: {k}")
        for k in ("criterion_type", "criterion_text", "trial_id"):
            if a["source"][k] != b["source"][k]:
                raise ValueError(f"Governing assignment drift in {case}: {k}")
        keys = sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))
        used_refs = set()
        for row in (a, b):
            for k in ("evidence", "partial_evidence"):
                used_refs.update(row["decision"].get(k, []))
        old_chart, chart = old_charts[a["subject"]], charts[b["subject"]]
        changed_evidence = sorted(ref for ref in used_refs if old_chart.get(ref) != chart.get(ref))
        if keys or changed_evidence:
            changed.append({"case": case, "study": b["study"], "subject": b["subject"],
                            "criterion_type": b["source"]["criterion_type"], "criterion": b["source"]["criterion_text"],
                            "baseline_state": a["state"], "candidate_state": b["state"], "changed_fields": keys,
                            "changed_used_resources": changed_evidence, "baseline_row_sha256": canon(a),
                            "candidate_row_sha256": canon(b), "cited_lines": b["cited_lines"],
                            "candidate_decision": b["decision"], "source_sha256": b["source_sha256"]})
    publisher = BENCHMARK / "round8/publisher/annotations.parquet"
    checked(publisher, PUBLISHER)
    import duckdb
    with duckdb.connect() as db:
        pairs = db.execute("SELECT annotation_id, expert_eligibility FROM read_parquet(?) WHERE NOT training",
                           [str(publisher)]).fetchall()
    gold = {str(i): LABELS[label] for i, label in pairs}
    if len(pairs) != 134 or old.keys() != gold.keys() or sum(v in DEFINITE for v in gold.values()) != 91:
        raise ValueError("Publisher label cohort differs from the frozen population")
    for item in changed:
        target = gold[item["case"]]
        item.update(baseline_result=adjudication(item["baseline_state"], target),
                    candidate_result=adjudication(item["candidate_state"], target))
    lost = [case for case in old if old[case]["state"] in DEFINITE and old[case]["state"] != new[case]["state"]]
    return {
        "baseline_freeze_sha256": BASELINE, "candidate_freeze_sha256": candidate_pin,
        "release_predictions_sha256": PRIOR, "publisher_sha256": PUBLISHER, "original_notes_sha256": NOTES,
        "baseline_outputs_sha256": bm["outputs"], "candidate_outputs_sha256": cm["outputs"],
        "catalog_sha256": {"baseline": bm["catalog_sha256"], "candidate": cm["catalog_sha256"]},
        "source": "Non-training NCBI TrialGPT criterion assignments; physician eligibility labels",
        "verified_original_assignments": len(released), "publisher_blind_projection_sha256": BLIND_ASSIGNMENTS,
        "baseline": strict_counts(old, gold), "candidate": strict_counts(new, gold),
        "lost_baseline_decision_cases": sorted(lost, key=int),
        "state_changes": sum(r["baseline_state"] != r["candidate_state"] for r in changed),
        "changed_rows_or_used_evidence": len(changed), "changes": changed,
        "changed_chart_subjects": sorted(s for s in charts if charts[s] != old_charts[s]),
        "candidate_false_or_unsupported_cases": sorted((case for case, r in new.items()
            if r["state"] in DEFINITE and r["state"] != gold[case]), key=int),
        "scorer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python": sys.version.split()[0], "duckdb": duckdb.__version__,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--candidate-sha256", required=True, help="Independently confirmed complete forecast freeze digest")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Use a new score directory")
    receipt = evaluate(args.baseline, args.candidate, args.candidate_sha256)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.out.parent) as work:
        result = Path(work) / "score"
        result.mkdir()
        (result / "score.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n")
        args.out.mkdir()
        result.replace(args.out)
    print(args.out / "score.json")
