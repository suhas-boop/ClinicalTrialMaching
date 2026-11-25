"""Offline product-membership and course regression checks, using synthetic FHIR records."""
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from evaluate import evaluate, key
from fixtures import DATE, LOCAL, make

ROOT = Path(__file__).resolve().parent


class Records:
    def __init__(self, cases):
        self.rows = {}
        for case in cases:
            for entry in make(case, ""):
                resource = entry["resource"]
                resource["meta"] = {"versionId": "1"}
                self.rows[key(resource)] = resource

    def call(self, path):
        if "?" not in path:
            return self.rows[path]
        url = urlsplit(path)
        patient, = parse_qs(url.query)["patient"]
        return {"type": "searchset", "entry": [
            {"resource": r} for r in self.rows.values()
            if r["resourceType"] == url.path and r.get("subject", {}).get("reference") == patient
        ]}


def check(records, case, catalog, expected):
    result = evaluate(records, "Patient/" + case + "-p", "Condition/" + case + "-current", DATE, catalog)
    assert result["outcome"] == expected, (case, expected, result["outcome"])
    return result


def main():
    catalog = json.loads((ROOT / "catalog.json").read_text())
    cases = json.loads((ROOT / "cases.json").read_text())
    records = Records(cases)
    for case in cases:
        check(records, case["id"], catalog, case["expected"])
    for course, expected in [("prior", "NOT_MET"), ("current", "MET")]:
        records.rows["MedicationRequest/paired-1"]["basedOn"] = [{"reference": "CarePlan/paired-" + course}]
        check(records, "paired", catalog, expected)

    # The fictional products use a private test namespace. They never enter the clinical catalog.
    catalog["system"] = LOCAL
    for ingredients, formulation, course, state, expected in [
        (["fixture-B", "3639"], "conventional solution", "current", "given", "MET"),
        (["3639", "fixture-B"], "conventional solution", "current", "given", "MET"),
        (["fixture-B", "fixture-C"], "conventional solution", "current", "given", "NOT_MET"),
        (["fixture-B", "3639"], "liposomal", "current", "given", "AUTHORING_HOLD"),
        (["fixture-B", "3639"], "conventional solution", None, "given", "MISSING_DATA"),
        (["fixture-B", "3639"], "conventional solution", "prior", "given", "MISSING_DATA"),
        (["fixture-B", "3639"], "conventional solution", "current", "order", "AUTHORING_HOLD"),
        ([], "conventional solution", "current", "given", "BINDING_HOLD"),
    ]:
        catalog["products"] = {"combo": {"ingredients": ingredients, "formulation": formulation}}
        records = Records([{"id": "demo", "meds": [["combo", course, state]]}])
        result = check(records, "demo", catalog, expected)
        if expected == "MET":
            assert result["medications"][0]["ingredients"] == ingredients
    print("19 existing dispositions and 8 ingredient-list checks passed offline.")


if __name__ == "__main__":
    main()
