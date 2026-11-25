"""Measure official same-patient diagnosis addenda in the existing screening engine.

The unmodified native matcher hashes one canonical source note per patient. Supply both
the independent source document and a separate, reversible composite for that input.
The composite has the frozen narrative verbatim followed by one templated presentation
of the organizer's recorded diagnosis. Source and projection offsets are retained.
"""
import argparse
import base64
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys
from source_join import digest, join

STAMP = "2026-01-01T00:00:00Z"  # replay clock, never interpreted as date of diagnosis


def project(note, extra, diagnosis_lexicon=()):
    attach = extra["fhir"]["content"][0]["attachment"]
    diagnosis = base64.b64decode(attach["data"], validate=True).decode()
    if diagnosis != extra["wording"] or "\n" in diagnosis:
        raise ValueError("Diagnosis differs from source attachment")
    # Subject attribution comes from the verified topic diagnosis field.
    # Use the frozen intake's established grammar for a native coded Condition when
    # an exact diagnosed concept exists, otherwise its current-patient grammar.
    predicate = "carries a diagnosis of" if " ".join(diagnosis.lower().split()) in diagnosis_lexicon else "has"
    template = "The patient " + predicate + " {verbatim diagnosis}."
    prefix = f"\n{len(note.splitlines())}. The patient {predicate} "
    combined = note + prefix + diagnosis + "."
    first = len(note + prefix)
    return combined, [first, first + len(diagnosis)], template


def load(path):
    return json.loads(path.read_text())


def resources(bundle):
    return [entry["resource"] for entry in bundle["entry"]]


def run(root):
    sys.path.insert(0, str(root / "round12"))
    from intake import plain_chart
    from screen import verify, screen
    from record_facts import DIAG
    pack = verify(load(root / "round11/compiled.json"))
    notes = load(root / "round9/notes.json")
    joined = join(root)
    assignments = [a for a in load(root / "round9/assignments.json") if joined[a["patient"]]["supplement"]]
    chart_cache = {}
    trials = []
    chart_summary = {}
    for a in assignments:
        patient = a["patient"]
        subject = "Patient/" + patient
        extra = joined[patient]["supplement"]
        if patient not in chart_cache:
            doc = extra["fhir"]
            if doc["subject"]["reference"] != subject:
                raise ValueError("Additional document belongs to another subject")
            note = notes[patient]
            combined, offsets, template = project(note, extra, DIAG)
            if combined[slice(*offsets)] != extra["wording"]:
                raise ValueError("Inexact projection")
            baseline = resources(plain_chart(patient, note, STAMP)[0])
            expanded, spans = plain_chart(patient, combined, STAMP)
            expanded = resources(expanded)
            original_doc = deepcopy(next(r for r in baseline if r["resourceType"] == "DocumentReference"))
            original_doc["id"] = patient + "-frozen-note"
            # DocumentReference.relatesTo retains both input documents on the composite.
            projected_doc = next(r for r in expanded if r["resourceType"] == "DocumentReference")
            projected_doc["description"] = "Research replay projection of frozen vignette and organizer's published diagnosis"
            projected_doc["relatesTo"] = [
                {"code": "transforms", "target": {"reference": "DocumentReference/" + item["id"]}}
                for item in (original_doc, doc)
            ]
            expanded.extend([original_doc, doc])
            chart_cache[patient] = (baseline, baseline + [doc], expanded)
            chart_summary[patient] = {
                "wording": extra["wording"], "source_url": extra["source_url"],
                "source_sha256": extra["source_sha256"], "locator": extra["locator"],
                "frozen_note_sha256": digest(note.encode()), "composite_sha256": digest(combined.encode()),
                "wording_in_composite": offsets, "projection_template": template,
                "source_fhir": "DocumentReference/" + doc["id"],
                "clinical_facts_extracted_from_diagnosis": [s for s in spans if len(note.splitlines()) in s["sentences"]],
            }
        key = str(a["annotation_id"])
        queries = [screen(items, subject, pack, a["study"], key) for items in chart_cache[patient]]
        states = [q["criteria"][key]["state"] for q in queries]
        frozen, attached, expanded = queries
        if frozen["source_sha256"] != attached["source_sha256"]:
            raise AssertionError("Detached document unexpectedly changed the canonical note")
        if expanded["source_sha256"] != chart_summary[patient]["composite_sha256"]:
            raise AssertionError("The engine did not read the supplementary projection")
        old = frozen["criteria"][key]
        current = expanded["criteria"][key]
        def clinical_values(c):
            return {k: [v["state"], v.get("value")] for k, v in c["facts"].items()}
        trials.append({
            "case": key, "study": a["study"], "subject": patient,
            "frozen": states[0], "attached_only": states[1], "expanded_source": states[2],
            "clinical_operand_changes": {k: [v, clinical_values(current)[k]] for k, v in clinical_values(old).items()
                                        if v != clinical_values(current)[k]},
            "expanded_evidence": current["evidence"], "expanded_source_hash_verified": True,
        })
    return {
        "joined_subjects": len(joined), "subjects_with_official_addenda": sum(bool(rec["supplement"]) for rec in joined.values()),
        "subjects_with_assigned_rules_and_addenda": len(chart_cache),
        "supplemental_subjects_without_assigned_rules": [p for p, rec in joined.items() if rec["supplement"] and p not in chart_cache],
        "assigned_criteria_replayed_per_arm": len(trials),
        "frozen": dict(Counter(r["frozen"] for r in trials)),
        "supplement_attached_only": dict(Counter(r["attached_only"] for r in trials)),
        "supplement_projected": dict(Counter(r["expanded_source"] for r in trials)),
        "eligibility_state_changes": [r["case"] for r in trials if r["frozen"] != r["expanded_source"]],
        "clinical_operand_changes": [r["case"] for r in trials if r["clinical_operand_changes"]],
        "subjects_with_extracted_supplemental_facts": [pat for pat, c in chart_summary.items() if c["clinical_facts_extracted_from_diagnosis"]],
        "subjects": chart_summary, "cases": trials,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.benchmark)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("subjects", "cases")}, indent=2))
