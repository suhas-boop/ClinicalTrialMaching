"""Retrospective chart-to-rule replay. A simulated C1D1 cannot establish an actual screening date."""
import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

from evidence_review import screen_snapshot, work_counts
from bindings import Snapshot, canonical, contract, instant, make_packet, UCUM
from screen_study import get_pack, ROOT
from runpy import run_path

M = json.loads(Path(__file__).with_name("platelet_contract.json").read_text())
LOINC = M["loinc_system"]


def lab_code(resource):
    return {c.get("code") for c in resource.get("code", {}).get("coding", []) if c.get("system") == LOINC}


def evidence_id(r):
    return r["resourceType"] + "/" + r["id"] + "#sha256=" + hashlib.sha256(canonical(r)).hexdigest()


def category(r, system, code):
    return any(c.get("system")==system and c.get("code")==code for cc in r.get("category",[]) for c in cc.get("coding",[]))


def day(value):
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d\d-\d\d", value):
        return date.fromisoformat(value)
    return instant(value).astimezone(timezone.utc).date()


def normalized_count(q, local, mapping=M):
    if not isinstance(q,dict) or q.get("comparator") or type(q.get("value")) not in (int,float):
        raise ValueError("Verify an exact numeric result.")
    code = q.get("code")
    kind = "UCUM"
    if not code and not q.get("system") and local and q.get("unit") in mapping["export_unit_aliases"]:
        code = mapping["export_unit_aliases"][q["unit"]]
        kind = "export_unit_alias"
    elif q.get("system") != UCUM:
        raise ValueError("Verify the source unit against the export crosswalk.")
    if code not in mapping["ucum_factors"]:
        raise ValueError("Unsupported unit for this analyte.")
    # Known display spellings cannot contradict the coded unit.
    known = {**mapping["export_unit_aliases"], **({"K/uL":"10*3/uL"} if "10*3/uL" in mapping["ucum_factors"] else {}), **{k:k for k in mapping["ucum_factors"]}}
    display = known.get(q.get("unit"))
    if q.get("unit") and (not display or mapping["ucum_factors"][display] != mapping["ucum_factors"][code]):
        raise ValueError("Conflicting coded and displayed unit.")
    value = Decimal(str(q["value"])) * Decimal(str(mapping["ucum_factors"][code]))
    if not value.is_finite() or value < 0:
        raise ValueError("Verify a finite nonnegative measurement.")
    if mapping["target_unit"]=="/mm3" and value!=value.to_integral_value():
        raise ValueError("Verify a whole cell count per cubic millimeter.")
    numeric=int(value) if value==value.to_integral_value() else float(value)
    if Decimal(str(numeric))!=value:
        raise ValueError("Measurement lost precision during conversion.")
    return numeric, kind


def chart_read(rows, subject, at, c1d1, local, chart=None, mapping=M, allow_repeats=False):
    """Link a final laboratory report to its exact result for the requested patient."""
    index = defaultdict(list)
    parents = defaultdict(list)
    for r in rows:
        if r.get("resourceType") not in {"Observation","DiagnosticReport"}:
            continue
        key = r["resourceType"]+"/"+r["id"]
        if r not in index[key]:
            index[key].append(r)
        if r["resourceType"]=="DiagnosticReport":
            for link in r.get("result",[]):
                parents[link.get("reference","").split("/_history/")[0]].append((r,link.get("reference")))
    proofs, issues = [], set()
    for key, history in index.items():
        candidates = [o for o in history if o["resourceType"]=="Observation" and
                      o.get("subject",{}).get("reference")==subject and mapping["loinc"] in lab_code(o)]
        for o in candidates:
            try:
                # A report issued in the future cannot establish or contradict a finding now.
                linked = parents.get(key, [])
                def visible(r):
                    times=[r.get("issued"),r.get("meta",{}).get("lastUpdated")]
                    return all(instant(t)<=at for t in times if t)
                if not visible(o):
                    continue
                available=[(r,t) for r,t in linked if visible(r)]
                if linked and not available:
                    continue
                od = day(o.get("effectiveDateTime"))
                delta = (c1d1-od).days
                if od > at.date() or (chart is None and not 1 <= delta <= mapping["calendar_days_before_c1d1"]):
                    continue
                if chart and not -1 <= delta <= mapping["calendar_days_before_c1d1"]+1:
                    continue
                if chart and available:
                    visits={r.get("encounter",{}).get("reference") for r,_ in available}
                    if None not in visits and chart.encounter not in visits:
                        continue
                    if all(not chart.eligible_time(instant(r["effectiveDateTime"])) for r,_ in available):
                        continue
                if len([v for v in history if visible(v)])!=1 or lab_code(o)!={mapping["loinc"]}:
                    raise ValueError("Ambiguous observation identity or analyte code.")
                if not category(o,"http://terminology.hl7.org/CodeSystem/observation-category","laboratory"):
                    raise ValueError("Verify laboratory classification.")
                if o.get("status")!="final" or o.get("implicitRules") or o.get("modifierExtension") or o.get("dataAbsentReason"):
                    raise ValueError("Verify current final result and applicable modifiers.")
                if [k for k in o if k.startswith("value")] != ["valueQuantity"]:
                    raise ValueError("Verify unambiguous quantitative result.")
                if o.get("issued") and instant(o["issued"])>at:
                    raise ValueError("Result was unavailable by the cutoff.")
                if o.get("specimen"):
                    raise ValueError("Explicit specimen reference needs independent verification.")
                if chart and not any(r.get("encounter",{}).get("reference")==chart.encounter for r,_ in available):
                    raise ValueError("Verify the report belongs to the documented screening encounter.")
                value, unit_source = normalized_count(o.get("valueQuantity"),local,mapping)
                links = available
                if not links:
                    raise ValueError("Retrieve the original report linking this observation.")
                for report, target in links:
                    if target != key and target != key+"/_history/"+str(o.get("meta",{}).get("versionId","")):
                        raise ValueError("Report references a different result version.")
                    repkey="DiagnosticReport/"+report["id"]
                    if (len([v for v in index[repkey] if visible(v)])!=1 or report.get("subject",{}).get("reference")!=subject
                        or report.get("status")!="final" or report.get("modifierExtension") or report.get("implicitRules")
                        or not category(report,"http://terminology.hl7.org/CodeSystem/v2-0074","LAB")):
                        raise ValueError("Verify report identity, patient, laboratory classification and final status.")
                    measured=instant(report["effectiveDateTime"])
                    issued=instant(report["issued"])
                    if measured.astimezone(timezone.utc).date()!=od or not measured<=issued<=at:
                        raise ValueError("Verify collection, report and availability dates.")
                    if o.get("issued") and not measured<=instant(o["issued"])<=at:
                        raise ValueError("Invalid observation issue time.")
                    if chart is None and issued.astimezone(timezone.utc).date()>=c1d1:
                        raise ValueError("Report availability before the assumed dose cannot be established.")
                    if len(o["effectiveDateTime"])>10 and instant(o["effectiveDateTime"])!=measured:
                        raise ValueError("Conflicting collection times.")
                    if report.get("specimen") or any(instant(r["meta"]["lastUpdated"])>at for r in (report,o) if r.get("meta",{}).get("lastUpdated")):
                        raise ValueError("Verify referenced specimen or later resource update.")
                    if chart:
                        if report.get("encounter",{}).get("reference")!=chart.encounter or (o.get("encounter") and o["encounter"].get("reference")!=chart.encounter):
                            raise ValueError("Report and result must belong to the screening encounter.")
                        if not chart.eligible_time(measured) or issued>=chart.anchor:
                            raise ValueError("Report outside the documented C1D1 assessment window.")
                    proof={"refs":[evidence_id(report),evidence_id(o)],"value":value,"unit":mapping["target_unit"],
                           "original_quantity":o["valueQuantity"],"unit_source":unit_source,
                           "collection":report["effectiveDateTime"],"issued":report["issued"]}
                    if proof not in proofs:
                        proofs.append(proof)
            except (ValueError,KeyError,TypeError,ArithmeticError) as err:
                issues.add(str(err))
    if not allow_repeats and len({p["value"] for p in proofs})>1:
        issues.add("Reconcile different qualifying measurements before choosing one.")
    if not proofs and not issues:
        issues.add("Retrieve an in-window final "+mapping["fact"]+" result and its report.")
    return proofs, sorted(issues)


def replay(rows, patient, screening_day, simulate=False, local=False, as_of=None, anchor_packet=None, hematology=False):
    study, cid, key = M["study"], M["criterion"], M["fact"]
    pack=get_pack(study)
    rule=pack["rules"][cid]
    spec=rule["facts"][key]
    if pack["protocol_sha256"]!=M["protocol_sha256"] or contract(spec)!=M["contract"] or spec["unit"]!=M["target_unit"]:
        raise ValueError("Released protocol or evidence contract changed.")
    at=datetime.combine(screening_day,datetime.max.time(),timezone.utc)
    if as_of is not None:
        at=instant(as_of).astimezone(timezone.utc)
        if at.date()<screening_day:
            raise ValueError("Review cutoff precedes the screening day.")
    chart=None
    if anchor_packet is not None:
        if simulate:
            raise ValueError("Select a documented or simulated C1D1.")
        anchor_ctx=anchor_packet["context"]
        if anchor_ctx.get("protocol_sha256")!=M["protocol_sha256"] or anchor_ctx["patient"]!=patient or instant(anchor_ctx["as_of"])!=at:
            raise ValueError("Anchor's protocol, subject or cutoff differs from this screening.")
        chart=run_path(str(ROOT/"prior_evidence/modules/duality_qtc.py"))["Chart"](anchor_packet["bundle"],anchor_ctx)
        if chart.start.astimezone(timezone.utc).date()!=screening_day:
            raise ValueError("Screening start differs from the supplied encounter.")
        event=chart.by_ref[anchor_ctx["first_dose_ref"]]
        if event.get("encounter",event.get("context",{})).get("reference")!=chart.encounter:
            raise ValueError("First dose is outside the study encounter.")
    # The generated context identifies a retrospective replay, not an enrollment record.
    packet=make_packet({cid:rule},{},study,pack["protocol_sha256"],patient=patient.removeprefix("Patient/"),stamp=at.isoformat())
    ctx=packet["context"]
    snap=Snapshot(packet["bundle"],ctx,study,pack["protocol_sha256"])
    initial=screen_snapshot({cid:rule},snap,ctx,study,pack["protocol_sha256"])
    c1d1=screening_day+timedelta(days=7) if simulate else None
    if chart:
        c1d1=chart.anchor.astimezone(chart.zone).date()
    if hematology:
        from hematology import panel
        return panel(rows, snap, ctx, rule, pack, c1d1, local, chart, screening_day, at)
    proofs,issues=(chart_read(rows,snap.patient,at,c1d1,local,chart) if c1d1 else ([],["Verify the actual study C1D1 date."]))
    if not issues:
        refs=sorted({ref for p in proofs for ref in p["refs"]})
        if chart:
            refs=sorted(set(refs+chart.refs))
        snap.native[contract(spec)] = (proofs[0]["value"],None,refs,"Final report-linked blood platelet count")
    result=screen_snapshot({cid:rule},snap,ctx,study,pack["protocol_sha256"])
    from rules_engine import evaluate
    platelet_nodes=[node for node in rule["expression"]["all"] if node.get("fact")==key]
    if len(platelet_nodes)!=1:
        raise ValueError("Platelet comparison changed in released rule.")
    platelet=evaluate({"facts":rule["facts"],"expression":platelet_nodes[0]},snap)
    requests=list(result["requests"])
    if not c1d1 and any(q["route"]=="retrieve_record" for q in requests):
        identity=hashlib.sha256(canonical([study,pack["protocol_sha256"],snap.patient,ctx["encounter"],str(screening_day),"documented-c1d1"])).hexdigest()
        requests.append({"id":identity,"route":"retrieve_record","request":issues[0],"criteria":[cid]})
    return {"evidence_requirement":{"catalog":M,"comparison":platelet_nodes[0]},
            "study":study,"criterion":cid,"source":rule["locator"],"protocol_sha256":pack["protocol_sha256"],
            "mode":("documented_"+chart.anchor_type+"_c1d1" if chart else "simulated_date_chart_replay" if simulate else "unanchored_chart_replay"),
            "cutoff":at.isoformat(),"documented_c1d1":str(c1d1) if chart else None,
            "screening_day_utc":str(screening_day),"assumed_c1d1":str(c1d1) if simulate else None,
            "before":initial["criteria"][cid]["state"],"platelet_clause":platelet["state"],"full_criterion":result["criteria"][cid]["state"],
            "evidence":proofs,"decision_evidence":result["criteria"][cid]["evidence"],"issues":issues,
            "work":work_counts(result["criteria"],requests),"remaining_requests":requests}


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("ndjson",type=Path)
    p.add_argument("--patient",required=True)
    p.add_argument("--as-of",help="Offset-qualified cutoff for an incremental review")
    p.add_argument("--anchor-packet",type=Path,help="Trusted protocol-pinned screening encounter and versioned C1D1 order or administration")
    p.add_argument("--screening-day",type=date.fromisoformat,required=True)
    p.add_argument("--simulate-c1d1-plus-seven",action="store_true")
    p.add_argument("--hematology",action="store_true",help="Run the platelet, hemoglobin and absolute neutrophil comparisons together")
    p.add_argument("--use-export-unit-aliases",action="store_true")
    args=p.parse_args()
    with args.ndjson.open() as f:
        rows=[json.loads(line) for line in f if line.strip()]
    print(json.dumps(replay(rows,args.patient,args.screening_day,args.simulate_c1d1_plus_seven,args.use_export_unit_aliases,args.as_of,json.loads(args.anchor_packet.read_text()) if args.anchor_packet else None,args.hematology),indent=2))
