"""Run the course-binding experiment against a disposable local R4 server."""
import argparse
import copy
import json
from pathlib import Path
from fhir_client import FHIR
from fixtures import make, DATE
from evaluate import evaluate

ROOT=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("endpoint")
    parser.add_argument("--out",type=Path,default=ROOT/"results.json")
    args=parser.parse_args()
    api=FHIR(args.endpoint)
    catalog=json.loads((ROOT/"catalog.json").read_text())
    cases=json.loads((ROOT/"cases.json").read_text())
    cap=api.call("metadata?_summary=true")
    assert cap["fhirVersion"]=="4.0.1"
    results=[]
    def check(label,patient_id,expected):
        base=api.prefix+patient_id
        r=evaluate(api,"Patient/"+base+"-p","Condition/"+base+"-current",DATE,catalog)
        results.append(dict(case=label,expected=expected,**r))
        print(label,r["outcome"],flush=True)
        assert r["outcome"]==expected, (label,r)
        return r
    for case in cases:
        rows=make(case,api.prefix)
        receipt=api.call("",{"resourceType":"Bundle","type":"transaction","entry":rows},"POST")
        assert all(e["response"]["status"].startswith("2") for e in receipt["entry"])
    for case in cases:
        check(case["id"],case["id"],case["expected"])
    # Change only the course reference on the same order for the same patient.
    base=api.prefix+"paired"
    path="MedicationRequest/"+base+"-1"
    order=api.call(path)
    mutations=[]
    for course,expected in [("prior","NOT_MET"),("current","MET")]:
        before=copy.deepcopy(order)
        order["basedOn"]=[{"reference":"CarePlan/"+base+"-"+course}]
        mutations.append({"changed_fields":[k for k in before if before[k]!=order[k]],"before":before["basedOn"],"after":order["basedOn"]})
        assert mutations[-1]["changed_fields"]==["basedOn"]
        api.call(path,order,"PUT")
        order=api.call(path)
        run=check("paired-relink-"+course,"paired",expected)
        assert any(m["product"][0]["code"]=="1191138" for m in run["medications"])
    out={"server":cap.get("software"),"fhirVersion":cap["fhirVersion"],"catalog":catalog["version"],
         "results":results,"paired_mutations":mutations}
    args.out.write_text(json.dumps(out,indent=2)+"\n")

if __name__=="__main__":
    main()
