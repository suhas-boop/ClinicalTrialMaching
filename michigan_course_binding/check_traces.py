"""Check invariants beyond matching the expected outcome strings."""
from pathlib import Path
import json
import sys

path=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).with_name("results.json")
receipt=json.loads(path.read_text())
by_case={r["case"]:r for r in receipt["results"]}
assert len(receipt["results"])==len(by_case)==19
assert all(r["expected"]==r["outcome"] for r in by_case.values())
trio=[by_case[name] for name in ("paired","paired-relink-prior","paired-relink-current")]
assert [r["outcome"] for r in trio]==["MET","NOT_MET","MET"]
def drug(r,number):
    return next(m for m in r["medications"] if m["product"][0]["code"]==number)
doses=[drug(r,"1191138") for r in trio]
assert len({d["administration"] for d in doses})==1
assert len({d["order"].split("/_history/")[0] for d in doses})==1
assert len({d["order"] for d in doses})==3
assert [d["binding"] for d in doses]==["current course","other course","current course"]
assert doses[0]["ingredient"]==doses[2]["ingredient"]=="3639"
assert drug(by_case["liposomal"],"1790128")["ingredient"]=="3639"
assert by_case["liposomal"]["outcome"]=="AUTHORING_HOLD"
assert drug(by_case["missing-link"],"1191138")["binding"]=="unresolved course"
assert by_case["patient-isolation"]["medications"]==[]
assert by_case["named-aim"]["named_regimen"]["components"]==["doxorubicin","ifosfamide","mesna"]
assert all(x["changed_fields"]==["basedOn"] for x in receipt["paired_mutations"])
print("19/19 expected dispositions. Stable administration and changed order versions confirmed.")
