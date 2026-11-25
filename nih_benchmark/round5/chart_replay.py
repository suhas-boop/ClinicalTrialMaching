"""Local evaluation on every platelet-report date. Write original resources only to an explicitly supplied private file."""
import argparse
from collections import Counter
from datetime import timedelta
from pathlib import Path
import sys,json
BASE=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(BASE/"criterion_workbench"))
from native_lab import M, lab_code, day, evidence_id, replay

def run(paths,private):
    counts,examples={},{}
    for label,path in enumerate(paths,1):
        rows=[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        obs=[r for r in rows if r["resourceType"]=="Observation" and M["loinc"] in lab_code(r)]
        subjects={r["subject"]["reference"] for r in obs}
        if len(subjects)!=1:raise ValueError("Supply separate single-patient files.")
        candidates=[r for r in rows if r.get("resourceType") in {"ServiceRequest","MedicationAdministration"}
                    and ("c1d1-first-dose" in json.dumps(r.get("code",{})) or any(tag.get("value")=="c1d1-first-dose" for tag in r.get("identifier",[])))
                    and r.get("subject",{}).get("reference") in subjects]
        counts[f"export_{label}/anchor_inventory"]={"normalized_first_dose_candidates":len(candidates)}
        days=sorted({day(r["effectiveDateTime"]) for r in obs})
        sources={evidence_id(r):r for r in rows}
        for name,sim,local in [("actual_available_context",False,True),("standard_units",True,False),("export_alias_enabled",True,True),("review_two_days_later",True,True)]:
            traces=[replay(rows,next(iter(subjects)),d,sim,local,
                           (d+timedelta(days=2)).isoformat()+"T23:59:59.999999Z" if name=="review_two_days_later" else None) for d in days]
            counts[f"export_{label}/{name}"]={"days":len(days),"platelet":dict(Counter(t["platelet_clause"] for t in traces)),
                   "criterion":dict(Counter(t["full_criterion"] for t in traces)),
                   "missing_reasons":dict(Counter(i for t in traces for i in t["issues"]))}
            if name=="export_alias_enabled":
                same_day = traces
            if name=="review_two_days_later":
                counts[f"export_{label}/{name}"]["transitions"]=dict(Counter(a["platelet_clause"]+" -> "+b["platelet_clause"] for a,b in zip(same_day,traces)))
            if name=="export_alias_enabled":
                for state in ("MET","NOT_MET"):
                    item=next((t for t in traces if t["platelet_clause"]==state),None)
                    if item:
                        refs={ref for e in item["evidence"] for ref in e["refs"]}
                        examples[f"export_{label}/{state}"]={"trace":item,"source_resources":{ref:sources[ref] for ref in sorted(refs)}}
    if private:
        private.write_text(json.dumps(examples,indent=2)+"\n")
    return counts

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("exports",nargs="+",type=Path)
    p.add_argument("--private-examples",type=Path)
    a=p.parse_args()
    print(json.dumps(run(a.exports,a.private_examples),indent=2))
