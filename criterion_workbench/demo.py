"""Exercise one criterion from each uploaded trial and one new synthetic trial offline."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXAMPLES = ROOT / "examples"
AGE = ["NEOK001-1-I02", "--site", str(EXAMPLES / "NEOK001-1-protocol.zip")]
PROGRESSION = ["106S01-I18", "--site", str(EXAMPLES / "106S01-protocol.zip")]
SCREEN = ["--patient", "synthetic-age-example", "--encounter", "synthetic-screen",
          "--as-of", "2026-11-20T10:00:00Z"]
AGE_RESPONSE = ["--response", str(EXAMPLES / "age-author.json")]
PROGRESSION_RESPONSE = ["--response", str(EXAMPLES / "i18-author.json")]


def call(state, *arguments, expected_exit=0):
    command = [sys.executable, "-B", str(ROOT / "pipeline.py"), "--state-dir", str(state), *map(str, arguments)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != expected_exit:
        raise RuntimeError(f"{arguments[0]} returned {result.returncode}: {result.stderr or result.stdout}")
    return json.loads(result.stdout)


def age_cases(state):
    chart_path = EXAMPLES / "patient-age.json"
    run = call(state, "run", *AGE, *AGE_RESPONSE, "--bundle", chart_path, *SCREEN)
    results = {"eighteenth_birthday": run["patient_result"]["patient_outcome"]}
    for name, birth in (("one_day_under", "2008-11-21"), ("birth_date_missing", None)):
        bundle = json.loads(chart_path.read_text())
        patient = bundle["entry"][0]["resource"]
        if birth is None:
            del patient["birthDate"]
        else:
            patient["birthDate"] = birth
        variant = state / (name + ".json")
        variant.write_text(json.dumps(bundle))
        results[name] = call(state, "screen", run["run_id"], "--bundle", variant, *SCREEN)["patient_outcome"]
    return run, results


def main():
    with tempfile.TemporaryDirectory(prefix="pocketmd-demo-") as scratch:
        state = Path(scratch)
        run, cases = age_cases(state)
        held = call(state, "run", *PROGRESSION, *PROGRESSION_RESPONSE)
        repeated = call(state, "run", *PROGRESSION, *PROGRESSION_RESPONSE)
        external = EXAMPLES / "intake-age"
        args = ["run", "POCKETMD-SYNTHETIC-AGE-I01", "--manifest", external / "manifest.json",
                "--protocol", external / "protocol.pdf", "--response", external / "author.json"]
        unreviewed = call(state, *args)
        reviewed = call(state, *args, "--review", external / "review.json", "--bundle", external / "patient.json",
                        "--patient", "fixture", "--encounter", "screen", "--as-of", "2026-11-20T12:00:00Z")
        compat = EXAMPLES / "compat"
        michigan = call(state,"run","MI-LMS-01","--site",compat/"NCT05653388-protocol.zip",
                        "--response",compat/"mi-reference-draft.json","--bundle",compat/"mi-patient.json",
                        "--patient","demo-compat-met-p","--episode","demo-compat-met-current","--as-of","2026-04-15T12:00:00Z")
        rec = call(state,"run","REC-1245-101-I05","--site",compat/"REC-1245-101-protocol.zip",
                   "--response",compat/"rec-reference-draft.json","--bundle",compat/"rec-patient.json",
                   "--patient","demo","--encounter","screen","--as-of","2026-05-01T19:00:00Z")
        print(json.dumps({
            "mode": "offline research replay, synthetic patient records",
            "age_criterion": {"state": run["state"], "patient_cases": cases,
                              "evidence_at_boundary": run["patient_result"]["evidence"]},
            "progression_criterion": {"state": held["state"], "new_questions": held["new_questions"],
                                      "binding_gaps": held["binding_gaps"],
                                      "new_questions_on_repeat": repeated["new_questions"],
                                      "new_binding_gaps_on_repeat": repeated["new_binding_gaps"]},
            "new_synthetic_trial": {"before_reference":unreviewed["state"], "after_reference":reviewed["state"],
                                    "on_21st_birthday":reviewed["patient_result"]["patient_outcome"]},
            "reference_replays":{"Michigan_index_episode":michigan["patient_result"]["patient_outcome"],
                                 "REC_adolescent_Lansky_70":rec["patient_result"]["patient_outcome"]},
        }, indent=2))


if __name__ == "__main__":
    main()
