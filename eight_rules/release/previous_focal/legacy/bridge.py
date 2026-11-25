"""Bridge to the frozen PocketMD Michigan and SOTIO criteria. All runs are local."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MICHIGAN = "NCT05653388"
SOTIO = "106S01"


def _execute(operation, packet):
    run = subprocess.run(
        [sys.executable, "-B", str(ROOT / "execute.py"), operation],
        input=json.dumps(packet, allow_nan=False), capture_output=True, text=True,
    )
    if run.returncode:
        raise ValueError(run.stderr.strip() or "Unable to evaluate the supplied snapshot.")
    return json.loads(run.stdout)


def run_sotio(bundle, patient, encounter, as_of, *, timezone_name="UTC", onboarding=None, trusted_signers=None):
    """Return existing 15 criterion results for a single patient, encounter and snapshot."""
    return _execute("sotio", dict(bundle=bundle, patient=patient, encounter=encounter, as_of=as_of,
                                  timezone_name=timezone_name, onboarding=onboarding, trusted_signers=trusted_signers or {}))


def run_michigan(bundle, patient, episode, as_of):
    """Return Michigan's three eligibility criteria on a normalized snapshot and a calendar-day cutoff."""
    return _execute("michigan", dict(bundle=bundle, patient=patient, episode=episode, as_of=as_of))


def michigan_demo(label):
    return _execute("michigan-demo", {"label":label})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    cmd = parser.add_subparsers(dest="operation", required=True)
    for command in ("michigan-demo","michigan-packet"):
        frozen = cmd.add_parser(command)
        frozen.add_argument("label")
    for name in ("michigan","sotio"):
        node = cmd.add_parser(name)
        node.add_argument("packet",type=Path,help="JSON object with bundle, patient, as_of and episode or encounter.")
    cmd.add_parser("regenerate")
    cmd.add_parser("verify")
    args = parser.parse_args()
    if args.operation in {"michigan-demo","michigan-packet"}:
        result = _execute(args.operation, {"label":args.label})
    elif args.operation == "regenerate":
        from generate import generate
        result = generate()
    elif args.operation == "verify":
        from verify_bridge import verify
        result = verify()
    else:
        packet = json.loads(args.packet.read_text())
        result = (run_michigan if args.operation=="michigan" else run_sotio)(**packet)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
