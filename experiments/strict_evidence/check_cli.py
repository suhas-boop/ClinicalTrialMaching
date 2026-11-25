"""Re-import each original note through the public CLI and check all 134 frozen decisions."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from zipfile import ZipFile

from jsonschema import Draft6Validator

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
BENCH = PROJECT / "nih_benchmark"


def read(path):
    return json.loads(path.read_bytes())


def cli(*args):
    return subprocess.check_output([sys.executable, "-B", str(PROJECT / "pocketmd.py"), *args])


def run(freeze):
    manifest = read(freeze / "freeze.json")
    data = (freeze / "predictions.json").read_bytes()
    if hashlib.sha256(data).hexdigest() != manifest["outputs"]["predictions.json"]:
        raise ValueError("Forecast file differs from freeze")
    notes = read(BENCH / "round9/notes.json")
    with ZipFile(BENCH / "round9/r4-schema.zip") as archive:
        schema = json.loads(archive.read("fhir.schema.json"))
    validator = Draft6Validator({"$ref":"#/definitions/Bundle","definitions":schema["definitions"]})
    bundles = {}
    count = 0
    with tempfile.TemporaryDirectory() as tmp:
        for row in json.loads(data):
            subject = row["subject"]
            pid = subject.split("/")[1]
            if subject not in bundles:
                note = Path(tmp) / (pid + ".txt")
                note.write_bytes(notes[pid].encode("utf-8"))
                path = Path(tmp) / (pid + ".json")
                cli("fhir-convert",str(path),"--note",str(note),"--patient",pid,
                    "--frozen-trialgpt","--recorded","2026-01-01T00:00:00Z")
                validator.validate(read(path))
                bundles[subject] = path
            result = json.loads(cli("fhir-screen","--bundle",str(bundles[subject]),"--subject",subject,
                                    "--study",row["study"],"--criterion",row["case"]))
            if (result["criteria"][row["case"]] != row["decision"] or result["requests"] != row["requests"]
                    or result["source_sha256"] != row["source_sha256"] or result["catalog_sha256"] != manifest["catalog_sha256"]):
                raise ValueError(f"Public interface disagrees with freeze for {row['case']}")
            count += 1
    if (len(bundles),count) != (44,134):
        raise ValueError("Unexpected benchmark population")
    return {"freeze_sha256":hashlib.sha256((freeze/"freeze.json").read_bytes()).hexdigest(),
            "original_subject_notes_converted":len(bundles), "schema_valid_fhir_r4_bundles":len(bundles),
            "matching_public_cli_traces":count,"catalog_sha256":manifest["catalog_sha256"]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("freeze",type=Path)
    print(json.dumps(run(ap.parse_args().freeze),indent=2))
