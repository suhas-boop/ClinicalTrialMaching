"""Count verifiable local report-to-observation links without exporting patient details."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re

import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / "eight_rules" / "release"))
from bindings import PROFILE

LOCAL = re.compile(r"Observation/([A-Za-z0-9.-]{1,64})(?:/_history/([A-Za-z0-9.-]{1,64}))?")


def audit(rows):
    observations = defaultdict(list)
    reports = []
    for obj in rows:
        if obj.get("resourceType") == "DiagnosticReport":
            reports.append(obj)
        elif obj.get("resourceType") == "Observation":
            observations[obj["id"]].append(obj)
    checks = Counter()
    for report in reports:
        patient = report.get("subject", {}).get("reference")
        for link in report.get("result", []):
            m = LOCAL.fullmatch(link.get("reference", ""))
            if not m:
                checks["unsupported_reference"] += 1
                continue
            candidates = observations.get(m[1], [])
            if m[2] is not None:
                candidates = [o for o in candidates if o.get("meta", {}).get("versionId") == m[2]]
            if len(candidates) != 1:
                checks["absent_or_ambiguous"] += 1
            elif not patient or candidates[0].get("subject", {}).get("reference") != patient:
                checks["subject_mismatch_or_missing"] += 1
            else:
                checks["linked_same_subject"] += 1
    return {"observations":sum(map(len,observations.values())), "reports":len(reports),
            "reports_with_result_links":sum(bool(r.get("result")) for r in reports),
            "reports_with_presented_form":sum(bool(r.get("presentedForm")) for r in reports),
            "observations_declaring_screening_profile":sum(PROFILE in o.get("meta",{}).get("profile",[])
                         for items in observations.values() for o in items), "reference_checks":dict(checks)}


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("ndjson",type=Path)
    args=p.parse_args()
    with args.ndjson.open() as f:
        print(json.dumps(audit(json.loads(l) for l in f if l.strip()),indent=2))
