"""Find documented reasons that a patient cannot enter a study at the indexed encounter."""
import argparse
import json
from collections import Counter
from pathlib import Path

from study_scope import assess, run as age_replay, DEFAULT_CATALOG, read_json, verify
from fever_gate import screen_fever, replay as fever_replay


def disposition(age, fever=None):
    findings = []
    if age["state"] == "EXCLUDED_BY_AGE_AT_PRESENTATION":
        findings.append({"gate": "registered_age_window", "receipt": age})
    if fever is not None and fever["state"] == "NOT_MET":
        if (fever["subject"], fever["study"]) != (age["subject"], age["study"]):
            raise ValueError("Cannot combine findings about different patients or studies")
        findings.append({"gate": "required_fever_duration", "receipt": fever})
    return {
        "study": age["study"], "subject": age["subject"],
        "disposition": "NOT_ELIGIBLE_AT_PRESENTATION" if findings else "CONTINUE_SCREENING",
        "decisive_findings": findings,
        "age_screen": {"state": age["state"], "reason": age["reason"]},
        "fever_duration": fever["state"] if fever else None,
    }


def evaluate_frozen():
    ages, fevers = age_replay(), fever_replay()
    by_pair = {(row["subject"], row["study"]): row for row in fevers["gates"]}
    if len(by_pair) != len(fevers["gates"]):
        raise ValueError("Duplicate fever-gate result")
    pairs = []
    for age in ages["receipts"]:
        result = disposition(age, by_pair.pop((age["subject"], age["study"]), None))
        result["assigned_criteria"] = age["assigned_criterion_ids"]
        pairs.append(result)
    if by_pair:
        raise ValueError("Fever-gate case missing from the frozen assignments")
    excluded = [p for p in pairs if p["decisive_findings"]]
    return {
        "assignments": ages["assignments"], "patient_study_pairs": len(pairs),
        "pair_dispositions": dict(Counter(p["disposition"] for p in pairs)),
        "age_screen_coverage": ages["pair_counts"],
        "criteria_in_excluded_pairs": sorted(i for p in excluded for i in p["assigned_criteria"]),
        "pair_results": pairs,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--subject")
    parser.add_argument("--study")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    query = (args.subject, args.study, args.bundle)
    if any(query):
        if not all(query):
            parser.error("Supply --bundle, --subject and --study together.")
        resources = [x["resource"] for x in read_json(args.bundle)["entry"]]
        pack = verify(read_json(DEFAULT_CATALOG))
        if not any(x["source"]["trial_id"] == args.study for x in pack["rules"].values()):
            parser.error("Unknown study in this catalog.")
        result = disposition(assess(resources, args.subject, args.study, pack),
                             screen_fever(resources, args.subject, args.study))
    else:
        result = evaluate_frozen()
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2) + "\n")
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
