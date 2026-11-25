"""Compare the unfiltered R17 intake with intake of the original vignette minus its NIH supplement."""
import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

UPSTREAM = "https://github.com/ncbi-nlp/TrialGPT/blob/97ba047695ca77bfe8d3634c10cbe10b0095929f/trialgpt_matching/run_matching.py#L28-L35"
ASSUMPTION = "The patient will provide informed consent, and will comply with the trial protocol without any practical issues."


def digest(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def resources(bundle):
    return [entry["resource"] for entry in bundle["entry"]]


def run(bench):
    sys.path.insert(0, str(bench / "round16"))
    from literal_scope import R11, frozen_assignments, plain_chart, read_json, screen, verify
    from convert import build_case

    notes = read_json(bench / "round9/notes.json")
    pack = verify(read_json(R11 / "compiled.json"))
    charts = {}
    states = Counter()
    changed = []
    pattern = re.compile(r"\n(\d+)\. " + re.escape(ASSUMPTION) + r"\Z")
    for row, subject, _, approved in frozen_assignments():
        pid, trial = row["patient"], row["study"]
        case = str(row["annotation_id"])
        if subject not in charts:
            raw = notes[pid]
            assert digest(raw) == approved[subject]
            suffix = pattern.search(raw)
            assert suffix and raw.count(ASSUMPTION) == 1
            removed = raw[:suffix.start()]
            stamp = "2026-01-01T00:00:00Z"
            if subject.startswith("Patient/"):
                before, _ = plain_chart(pid, raw, stamp)
                after, _ = plain_chart(pid, removed, stamp)
            else:
                before = read_json(bench / "round9/export/bundles" / (pid + ".json"))
                after, _ = build_case(pid, removed, [], {}, {}, stamp)
            charts[subject] = resources(before), resources(after), int(suffix[1]), digest(removed)
        before_chart, after_chart, last, stripped_hash = charts[subject]
        before = screen(before_chart, subject, pack, trial, case)
        after = screen(after_chart, subject, pack, trial, case)
        assert before["source_sha256"] == approved[subject]
        assert after["source_sha256"] == stripped_hash
        previous, current = before["criteria"][case], after["criteria"][case]
        if previous["state"] in {"MET", "NOT_MET"}:
            assert last not in previous["source_sentences"]
        states[current["state"]] += 1
        if previous["state"] != current["state"]:
            changed.append([subject, trial, case, previous["state"], current["state"]])
    return dict(status="SOURCE_ABLATION_ONLY", upstream=UPSTREAM, subjects=len(charts),
                assignments=sum(states.values()), after=dict(states), changed=changed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bench", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    args.out.write_text(json.dumps(run(args.bench.resolve()), indent=2) + "\n")
