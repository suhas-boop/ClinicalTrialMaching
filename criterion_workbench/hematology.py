"""Evaluate simple I07 lower bounds for all usable readings at a screening cutoff."""
import hashlib
import json
from pathlib import Path

from bindings import contract
from evidence_review import screen_snapshot, work_counts
from native_lab import M, chart_read
from rules_engine import OPS

EXTRA=json.loads(Path(__file__).with_name("hematology_contracts.json").read_text())
REPEAT_QUESTION=("For DB-1311-O-1001 v6 I07, when two valid screening measurements fall on opposite "
                 "sides of the threshold before C1D1, which collection governs eligibility, and "
                 "when must the site record a new screening attempt?")


def panel(rows, snap, ctx, rule, pack, c1d1, local, chart, screening_day, at):
    study,cid,version=M["study"],M["criterion"],pack["protocol_sha256"]
    fields={}
    # The released rule must use each of these facts exactly once as a top-level
    # conjunct. Otherwise the two extremal evaluations below do not suffice.
    def uses(node,key):
        if isinstance(node,list):return sum(uses(n,key) for n in node)
        if not isinstance(node,dict):return 0
        return int(node.get("fact")==key)+sum(uses(v,key) for v in node.values())

    for mapping in [M,*({**M,**spec} for spec in EXTRA)]:
        key=mapping["fact"]
        fact=rule["facts"][key]
        nodes=[n for n in rule["expression"]["all"] if n.get("fact")==key]
        if (contract(fact)!=mapping["contract"] or fact["unit"]!=mapping["target_unit"] or
                len(nodes)!=1 or nodes[0].get("op")!="ge" or uses(rule["expression"],key)!=1 or uses(rule.get("applies"),key)):
            raise ValueError("Released comparison or evidence mapping changed.")
        threshold=nodes[0]["value"]
        proofs,issues=(chart_read(rows,snap.patient,at,c1d1,local,chart,mapping,True) if c1d1
                       else ([],["Verify the actual trial C1D1 date."]))
        values=sorted({p["value"] for p in proofs})
        outcomes={OPS["ge"](v,threshold) for v in values}
        state="MISSING_DATA"
        if not issues and len(outcomes)==1:
            state="MET" if outcomes=={True} else "NOT_MET"
        refs=sorted({ref for p in proofs for ref in p["refs"]} | (set(chart.refs) if chart and proofs else set()))
        fields[key]={"state":state,"threshold":threshold,"operator":"ge","unit":fact["unit"],"loinc":mapping["loinc"],
                     "values":values,"issues":issues,"straddles":not issues and len(outcomes)==2,"refs":refs,"proofs":proofs}
    trials=[]
    for boundary in (min,max):
        for key,field in fields.items():
            if field["state"] in {"MET","NOT_MET"}:
                snap.native[contract(rule["facts"][key])]=(boundary(field["values"]),None,field["refs"],"Verified measurement")
        trials.append(screen_snapshot({cid:rule},snap,ctx,study,version))
    review=trials[0]
    verdict=review["criteria"][cid]
    if (verdict["state"],verdict["evidence"],review["requests"])!=(
            trials[1]["criteria"][cid]["state"],trials[1]["criteria"][cid]["evidence"],trials[1]["requests"]):
        raise ValueError("The criterion depends on which qualified measurement is selected.")
    pending=list(review["requests"])
    def task(route,name,question,scope):
        identifier=hashlib.sha256(json.dumps([study,version,route,name,*scope]).encode()).hexdigest()
        return {"id":identifier,"route":route,"request":question,"criteria":[cid]}
    if verdict["state"]=="MISSING_DATA":
        if not c1d1:
            pending.append(task("retrieve_record","first-dose","Retrieve the trial-specific cycle 1 day 1 order or administration.",
                                [snap.patient,str(screening_day)]))
        disputed=[k for k,v in fields.items() if v["straddles"]]
        if disputed:
            # Replace the generic lookup for an already retrieved disputed fact.
            known_scopes={rule["facts"][k]["scope"] for k in disputed}
            pending=[q for q in pending if not(q["route"]=="retrieve_record" and q["request"] in known_scopes)]
            pending.append(task("protocol_review","I07-repeat-selection",REPEAT_QUESTION,[]))
    return {"study":study,"protocol_sha256":version,"criterion":cid,"source":rule["locator"],
            "mode":("documented_"+chart.anchor_type if chart else "simulated_c1d1" if c1d1 else "unanchored"),
            "screening_day":str(screening_day),"cutoff":at.isoformat(),"c1d1":str(c1d1) if c1d1 else None,
            "fields":fields,"full_criterion":verdict["state"],"decision_evidence":verdict["evidence"],
            "requests":pending,"work":work_counts(review["criteria"],pending)}
