"""Compare both readers on precisely the R5 cohort. Publish aggregate counts only."""
import argparse
from collections import Counter
from datetime import timedelta
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"criterion_workbench"))
from native_lab import replay,day,lab_code,M,evidence_id,instant

# Presence-only lookup using identifiers in the bundled lab mapping inventory.
LOOKUP={"serum_albumin":"1751-7","ast":"1920-8","alt":"1742-6","total_bilirubin":"1975-2","inr":"6301-6"}

def available_codes(rows,subject,first,asof):
    obs={"Observation/"+r["id"]:r for r in rows if r["resourceType"]=="Observation" and r.get("subject",{}).get("reference")==subject}
    found=set()
    for r in rows:
        if (r["resourceType"]!="DiagnosticReport" or r.get("status")!="final" or
            r.get("subject",{}).get("reference")!=subject or not r.get("issued") or instant(r["issued"])>instant(asof)):
            continue
        for link in r.get("result",[]):
            o=obs.get(link.get("reference"))
            if o and o.get("status")=="final" and 1<=(first-day(o["effectiveDateTime"])).days<=7:
                found.update(lab_code(o))
    return found

def compare(paths):
    summary={}
    for mode,offset,simulate in [("unanchored",0,False),("screening_day",0,True),("two_days_later",2,True)]:
        stats={name:Counter() for name in ("old_full","new_full","full_transitions","platelets","hemoglobin","anc","old_open_platelets","new_deciding_failures","remaining_straddles")}
        human=set(); examples=[];n=0; candidate_days=Counter()
        for file in paths:
            rows=[json.loads(l) for l in file.read_text().splitlines() if l.strip()]
            platelet=[r for r in rows if r["resourceType"]=="Observation" and M["loinc"] in lab_code(r)]
            subject,={r["subject"]["reference"] for r in platelet}
            for d in sorted({day(r["effectiveDateTime"]) for r in platelet}):
                params=dict(simulate=simulate,local=True,as_of=(d+timedelta(days=offset)).isoformat()+"T23:59:59.999999Z")
                old=replay(rows,subject,d,**params);new=replay(rows,subject,d,hematology=True,**params);n+=1
                a,b=old["full_criterion"],new["full_criterion"]
                stats["old_full"][a]+=1;stats["new_full"][b]+=1;stats["full_transitions"][a+" to "+b]+=1
                for k,f in new["fields"].items():
                    stats[k][f["state"]]+=1
                    if f["straddles"] and b=="MISSING_DATA":stats["remaining_straddles"][k]+=1
                if old["platelet_clause"]=="MISSING_DATA":stats["old_open_platelets"][new["fields"]["platelets"]["state"]]+=1
                if a=="MISSING_DATA" and b=="NOT_MET":
                    failed=[k for k,f in new["fields"].items() if f["state"]=="NOT_MET"]
                    stats["new_deciding_failures"][" + ".join(failed)]+=1
                    idx={evidence_id(r) for r in rows}
                    assert new["decision_evidence"] and set(new["decision_evidence"])<=idx
                    if not examples:examples.append({k:{"values":new["fields"][k]["values"],"unit":new["fields"][k]["unit"]} for k in failed})
                if simulate and b=="MISSING_DATA":
                    codes=available_codes(rows,subject,d+timedelta(days=7),params["as_of"])
                    if {LOOKUP[k] for k in ("serum_albumin","ast","alt","total_bilirubin")} <= codes:
                        candidate_days["all_four_chemistry_codes"]+=1
                    for field,code in LOOKUP.items():
                        if code in codes: candidate_days[field]+=1
                human.update(q["id"] for q in new["requests"] if q["route"]=="protocol_review")
        summary[mode]={"scenarios":n,**stats,"distinct_protocol_questions":len(human),"first_new_example":examples,"available_report_codes_on_still_open_dates":candidate_days}
    return summary

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("exports",nargs="+",type=Path)
    print(json.dumps(compare(p.parse_args().exports),indent=2))
