"""Rebuild the blinded predictions, verify their freeze, then score in a new process."""

import argparse
import json
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="a new directory for this replay")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    predictions = output / "predictions"
    subprocess.run(
        [sys.executable, "-B", str(HERE / "predict.py"), "--out", str(predictions),
         "--verify-against", str(HERE / "author" / "frozen")],
        check=True,
    )
    subprocess.run(
        [sys.executable, "-B", str(HERE / "evaluator" / "score.py"),
         "--freeze", str(predictions), "--out", str(output / "score")],
        check=True,
    )
    result = output / "score" / "score.json"
    actual = json.loads(result.read_bytes())
    expected = json.loads((HERE / "evaluator" / "verified" / "score.json").read_bytes())
    # These fields describe the local implementation that produced each score.
    for record in (actual, expected):
        record.pop("sqlite_version")
        record.pop("evaluator_sha256")
    if actual != expected:
        raise SystemExit(f"Replay differs from the independently verified score. Inspect {result}")
    print(f"Reproduced the verified score in {result}")


if __name__ == "__main__":
    main()
