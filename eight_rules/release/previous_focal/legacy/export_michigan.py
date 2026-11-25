"""Export the 38 original Michigan synthetic patient packets for the unified study runner."""
import argparse
import json
from pathlib import Path

try:
    from .bridge import MICHIGAN, ROOT, _execute
except ImportError:
    from bridge import MICHIGAN, ROOT, _execute


def export_michigan(output_dir=None):
    output = Path(output_dir) if output_dir else (
        ROOT.parent / ("release/examples" if (ROOT.parent/"release").is_dir() else "examples")
    )
    output.mkdir(parents=True, exist_ok=True)
    traces = json.loads((ROOT / "legacy_replays.json").read_text())[MICHIGAN]
    paths = []
    for label, trace in traces.items():
        fixture = _execute("michigan-packet", {"label":label})
        packet = {"context": {"study":MICHIGAN, "protocol_sha256":trace["protocol_sha256"],
                             "mode":"synthetic_demo", "patient":fixture["patient"],
                             "episode":fixture["episode"], "as_of":fixture["as_of"]},
                  "bundle":fixture["bundle"]}
        path = output / ("michigan-"+label+".json")
        path.write_text(json.dumps(packet,ensure_ascii=False,indent=2)+"\n")
        paths.append(path)
    return paths


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    written=export_michigan(args.output)
    print(f"Wrote {len(written)} Michigan packets in {written[0].parent}")
