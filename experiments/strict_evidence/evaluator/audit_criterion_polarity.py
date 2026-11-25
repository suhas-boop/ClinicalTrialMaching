"""Audit every counted agreement against the registry, after checking the strict freeze."""
import json
import sys
from pathlib import Path

import duckdb
import score

EXPERIMENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPERIMENT))
from audit import FrozenReads, evaluate, registry

RELEASE = "d9c178f289e77d28d16661a741230fbe0a0fbc9d1c553a5970ac6d696490cf7d"
REGISTRY_MANIFEST = "2084977c389f84301d2aa40ed45aff401f2ec7af00704f24c80e1fc39f42a0da"


def normalize(text):
    return " ".join(text.casefold().split())


def run():
    folder = EXPERIMENT / "release"
    verified = score.evaluate(EXPERIMENT / "baseline", folder, RELEASE)
    rows = score.indexed(json.loads((folder / "predictions.json").read_bytes()), "case")
    publisher = score.BENCHMARK / "round8/publisher/annotations.parquet"
    with duckdb.connect() as db:
        annotations = db.execute("""
            SELECT annotation_id, trial_id, patient_id, criterion_type, criterion_text, expert_eligibility
            FROM read_parquet(?) WHERE NOT training ORDER BY annotation_id
        """, [str(publisher)]).fetchall()

    archive = score.BENCHMARK / "round17/registry/benchmark_2015"
    manifest = json.loads(score.checked(archive / "manifest.json", REGISTRY_MANIFEST))
    selection = manifest["dataset"]["nih_source"]
    trials = json.loads(score.checked(archive / selection["selected_path"], selection["selected_sha256"]))
    counted = []
    gold = {}
    sensitivity_rows = rows.copy()
    for identifier, study, patient, assigned, clause, label in annotations:
        case = str(identifier)
        row = rows[case]
        source = {"criterion_type": assigned, "criterion_text": clause, "trial_id": study}
        if any(row["source"][key] != value for key, value in source.items()) or patient != row["subject"].split("/", 1)[1]:
            raise ValueError(f"Publisher identity or criterion differs in {case}")
        gold[case] = score.LABELS[label]
        if row["state"] not in score.DEFINITE or row["state"] != gold[case]:
            continue
        entry = manifest["studies"][study]
        score.checked(archive / entry["path"], entry["sha256"])
        historical = registry(source, case, manifest["studies"])
        heading = historical["heading_at_match"]
        nih_sections = [side for side in ("inclusion", "exclusion")
                        if normalize(clause) in normalize(trials[study][side + "_criteria"])]
        if not historical["release_version_verified"] or nih_sections != [heading]:
            raise ValueError(f"Study sources do not establish a unique matching section for {case}")

        rule = row["rule"]
        snapshot = FrozenReads(row)
        decision = evaluate(rule, snapshot)
        if decision["state"] != row["state"] or decision["evidence"] != row["decision"]["evidence"]:
            raise ValueError(f"Frozen decision or supporting resources differ on replay for {case}")
        if heading != assigned:
            # The published inclusion expression is the positive predicate.
            # Under the registry exclusion an observed positive excludes.
            if assigned != "inclusion" or heading != "exclusion":
                raise ValueError(f"Unexpected polarity change in {case}")
            decision = evaluate(dict(rule, expression={"not": rule["expression"]}), snapshot)
            sensitivity_rows[case] = dict(row, state=decision["state"])
        counted.append(dict(case=case, study=study, subject=row["subject"], clause=clause,
                            assigned_type=assigned, expert_eligibility=label, mapped_state=gold[case],
                            frozen_state=row["state"], frozen_expression=rule["expression"],
                            cited_lines=row["cited_lines"], evidence=decision["evidence"],
                            nih_trial_info_section=nih_sections[0], historical_registry=historical,
                            registry_oriented_state=decision["state"]))
    if len(counted) != verified["candidate"]["agree"]:
        raise ValueError("Agreement count differs from the strict replay")
    return dict(baseline_freeze_sha256=score.BASELINE, release_freeze_sha256=RELEASE,
                publisher_sha256=score.PUBLISHER, catalog_sha256=verified["catalog_sha256"]["candidate"],
                registry_manifest_sha256=REGISTRY_MANIFEST, nih_selection_sha256=selection["selected_sha256"],
                published_baseline=verified["baseline"], published_release=verified["candidate"],
                counted_cases=counted,
                source_polarity_conflicts=[r["case"] for r in counted if r["assigned_type"] != r["nih_trial_info_section"]],
                sensitivity_method="Only reorient registry-discordant counted predictions. Compare to the original published physician labels. This is a sensitivity check.",
                sensitivity_against_unchanged_labels=score.strict_counts(sensitivity_rows, gold))


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, ensure_ascii=False))
