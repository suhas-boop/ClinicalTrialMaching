"""Verify the stored public annotation and schema against the pinned dev split."""
import argparse
import hashlib
import json
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parent
REVISION = "045528d70a7d788775a24763adfed6c66023c914"
DEV_LINE = 242
SCHEMA_LINE = 50
FILES = {
    "dev.jsonl": (
        "00dbac8202e0f3b1c8ec85dfc333c6bafb2f92e60ab3f3242bcc38a3b2a89f4b",
        "4bc319b4a79791721c63779d7e9222971bd79a74",
    ),
    "dev.tables.jsonl": (
        "102ac079098d1015532752b68bdbdbc15ca98270958f118636d6d2edb5e4ac54",
        "d91e89a56ed8465024be0a71a0d3608217992483",
    ),
}


def verified_line(source_dir, name, line_number):
    data = (Path(source_dir) / name).read_bytes()
    sha256, git_blob = FILES[name]
    git_prefix = f"blob {len(data)}\0".encode("ascii")
    if hashlib.sha256(data).hexdigest() != sha256 or hashlib.sha1(git_prefix + data).hexdigest() != git_blob:
        raise ValueError(f"Pinned source hash mismatch for {name}")
    return data.splitlines(keepends=True)[line_number - 1]


def verify(source_dir):
    line = verified_line(source_dir, "dev.jsonl", DEV_LINE)
    if (DIRECTORY / "reference.jsonl").read_bytes() != line:
        raise ValueError("Selected annotation differs from the upstream bytes")
    table = json.loads(verified_line(source_dir, "dev.tables.jsonl", SCHEMA_LINE))
    schema = {key: table[key] for key in ("id", "header", "types")}
    if json.loads((DIRECTORY / "schema.json").read_bytes()) != schema:
        raise ValueError("Selected schema differs from upstream")
    if json.loads(line)["table_id"] != schema["id"]:
        raise ValueError("Selected table and annotation disagree")
    return {"revision": REVISION, "verified_files": sorted(FILES), "annotation_line": DEV_LINE, "schema_line": SCHEMA_LINE}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path, help="Directory containing upstream dev.jsonl and dev.tables.jsonl")
    print(json.dumps(verify(parser.parse_args().source_dir), indent=2))
