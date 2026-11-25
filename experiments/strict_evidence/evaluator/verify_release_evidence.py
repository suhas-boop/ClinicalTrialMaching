"""Recheck final source links and exercise independent post-imaging attribution controls."""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
sys.path.insert(0, str(PROJECT / "nih_benchmark/round12"))
from intake import plain_chart
from screen import R11, read_json, screen, verify

CAUSAL_FACT = "neurologic_symptoms_nonvascular_origin_after_ct_or_mri"


def source_links():
    folder = HERE.parent / "release"
    charts = json.loads((folder / "charts.json").read_bytes())
    rows = json.loads((folder / "predictions.json").read_bytes())
    related = []
    partial = {}
    for row in rows:
        decision = row["decision"]
        chart = charts[row["subject"]]
        if "partial_source_sentences" in decision:
            assert decision["state"] not in {"MET", "NOT_MET"} and decision["partial_evidence"]
            expected = sorted({i for ref in decision["partial_evidence"] for i in chart[ref]["lines"]})
            assert decision["partial_source_sentences"] == expected
            partial[row["case"]] = expected
        for fact in decision["facts"].values():
            for item in fact.get("related_findings", []):
                indexed = chart[item["resource"]]
                resource = indexed["resource"]
                if resource["code"]["coding"][0]["code"] != "documented-stroke-episode-with-linked-brain-imaging":
                    continue
                assert resource["resourceType"] == "Observation" and resource["status"] == "final"
                assert resource["subject"]["reference"] == row["subject"] and resource["valueBoolean"] is True
                assert resource["derivedFrom"] == [{"reference": "DocumentReference/" + row["subject"].split("/")[1] + "-note"}]
                assert indexed["lines"] == item["source_lines"]
                assert not set(decision["evidence"] + decision["partial_evidence"]) and not decision["source_sentences"]
                assert fact["value"] is None and fact["state"] == decision["state"] == "MISSING_DATA"
                related.append((row["case"], item["source_lines"]))
    assert related == [("817", [0, 1])]
    assert partial == {"26": [0], "55": [0], "132": [0], "230": [0], "323": [0], "454": [0], "460": [5], "795": [0]}
    return partial, related


def controls():
    # These fixtures were written by the independent verifier after freezing, without reference to physician rationales.
    pack = verify(read_json(R11 / "compiled.json"))
    key = "817"
    study = pack["rules"][key]["source"]["trial_id"]
    vascular = "After review of this cranial MRI, the neurologist attributed this patient's presenting neurological symptoms to an acute ischaemic stroke."
    nonvascular = "After CT of the head, the final neurological assessment attributed the presenting symptoms to a non-vascular origin."
    pair = ("A 63-year-old man was discharged with a confirmed ischemic stroke yesterday.\n"
            "During that episode, brain MRI revealed an acute infarction.")
    counterexample = ("He was hospitalized for cryptogenic stroke two weeks ago.\n"
                      "At that time, head CT was negative for intracranial bleeding.")
    cases = [
        ("vascular assessment", vascular, "MET", [0]),
        ("nonvascular assessment", nonvascular, "NOT_MET", [0]),
        ("prior diagnosis and completed CT", counterexample, "MISSING_DATA", []),
        ("infarct without attribution", pair, "MISSING_DATA", []),
        ("same episode plus attributed cause", pair + "\n" + vascular, "MET", [2]),
        ("different person", vascular.replace("this patient's", "his father's"), "MISSING_DATA", []),
        ("withdrawn assessment", nonvascular + "\nThe subsequent specialist overruled this opinion.", "MISSING_DATA", []),
        ("conflicting assessments", vascular + "\n" + nonvascular, "MISSING_DATA", []),
    ]
    for name, note, expected, lines in cases:
        bundle, _ = plain_chart("source-audit", note, "2026-01-01T00:00:00Z")
        resources = [item["resource"] for item in bundle["entry"]]
        actual = screen(resources, "Patient/source-audit", pack, study, key)["criteria"][key]
        if (actual["state"], actual["source_sentences"]) != (expected, lines):
            raise ValueError(f"{name}: {actual['state']}, lines {actual['source_sentences']}")
        if name in {"infarct without attribution", "prior diagnosis and completed CT"}:
            assert actual["facts"][CAUSAL_FACT]["related_findings"][0]["source_lines"] == [0, 1]
        print(name, actual["state"], actual["source_sentences"])


if __name__ == "__main__":
    partial, related = source_links()
    print("Audited partial facts", partial, "and separate related findings", related)
    controls()
