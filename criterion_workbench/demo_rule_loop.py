"""Run the recorded authoring, investigator clarification and FHIR screening examples."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "examples" / "text_workflow"


def cli(*args):
    run = subprocess.run([sys.executable, str(ROOT / "rules.py"), *map(str, args)],
                         capture_output=True, text=True)
    if run.returncode:
        raise RuntimeError(f"{args[0]} failed: {run.stderr or run.stdout}")
    return json.loads(run.stdout)


def check(label, actual, expected):
    if actual != expected:
        raise ValueError(f"{label}: expected {expected!r}, got {actual!r}")
    return actual


def run_demo(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    cases = json.loads((DATA / "cases.json").read_text())
    provider = ["--model-command", shlex.join([sys.executable, str(DATA / "replay.py")])]
    study = "DEMO-SARCOMA"

    def scope(case, trial=study, version="research-v1"):
        return ["--work", out / "work", "--study", trial, "--version", version, "--id", case]

    def build(key, packet, trial=study, version="research-v1"):
        source = cases[packet]
        polarity = ["--polarity", source["polarity"]] if "polarity" in source else []
        return cli("build", *scope(key, trial, version), "--criterion", source["criterion"],
                   "--context", source["protocol"], *polarity, *provider)

    def answer(key, packet):
        return cli("answer", *scope(key), "--question", "Q1", "--reviewer", "Simulated study investigator",
                   "--answer", cases[packet]["answer:Q1"], *provider)

    def screen_export(key, trial=study, version="research-v1", bundle=DATA / "patient-score-2.json",
                      patient="demo", encounter="screen", cutoff="2026-05-01T19:00:00Z"):
        path = out / (key + ".rule.json")
        cli("export", *scope(key, trial, version), "--out", path)
        return cli("screen", "--rule", path, "--bundle", bundle, "--patient", patient,
                   "--encounter", encounter, "--study", trial, "--version", version,
                   "--id", key, "--as-of", cutoff)

    clear = build("COMBINED", "clear")
    check("complete age and ECOG rule", clear["status"], "EXECUTABLE")
    combined = screen_export("COMBINED")
    check("combined on ECOG 2", combined["state"], "NOT_MET")

    paths = {}
    for packet, expected in (("answered_narrow", "NOT_MET"), ("answered_wide", "MET"),
                             ("answered_unclear", "INVESTIGATOR_REVIEW")):
        key = packet.upper()
        initial = build(key, "open")
        if not initial["answers"]:
            check("open eligibility", initial["status"], "INVESTIGATOR_REVIEW")
            check("open rule withheld", initial["rule_sha256"], None)
        final = answer(key, packet)
        case = {"question": cases[packet]["question:Q1"], "answer": cases[packet]["answer:Q1"],
                "authoring": final["status"]}
        if packet == "answered_unclear":
            check("nonspecific answer", final["status"], expected)
            check("nonspecific answer rule", final["rule_sha256"], None)
            case["followup"] = final["questions"]
        else:
            check("clarified authoring", final["status"], "EXECUTABLE")
            result = screen_export(key)
            case.update(expression=final["expression"], patient_state=check("same patient", result["state"], expected),
                        evidence=result["evidence"])
        paths[packet] = case

    unmapped = build("UNMAPPED", "unmapped")
    check("unsupported measurement", unmapped["status"], "BINDING_REVIEW")
    check("no partial publication", unmapped["rule_sha256"], None)
    check("no investigator question for missing mapping", unmapped["questions"], [])

    exclusion = build("EXCLUSION", "exclusion")
    check("exclusion authoring", exclusion["status"], "EXECUTABLE")
    excluded = screen_export("EXCLUSION")
    check("patient clear of exclusion", excluded["state"], "MET")

    neok = build("NEOK001-1-I02", "neok_age", "NEOK001-1", "amendment-2")
    check("age at encounter versus whole screening period", neok["status"], "BINDING_REVIEW")
    check("period start not verified", neok["rule_sha256"], None)
    neok_result = {"status": neok["status"], "reason": neok["reason"]}
    return {"mode": "exact replay of in-session model responses; synthetic patients and reviewer answers",
            "clear": {"expression": clear["expression"], "patient_state": combined["state"]},
            "clarification": paths,
            "missing_binding": {"status": unmapped["status"], "gaps": unmapped["gaps"]},
            "exclusion": {"expression": exclusion["expression"], "patient_state": excluded["state"]},
            "neok_uploaded_criterion": neok_result}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="Keep the case history and exported rules in this directory")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        result = run_demo(args.out if args.out else tmp)
        print(json.dumps(result, indent=2, ensure_ascii=False))
