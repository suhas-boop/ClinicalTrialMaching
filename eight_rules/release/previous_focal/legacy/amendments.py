"""Protocol-specific boundaries layered over the frozen research evaluator."""
from copy import copy
from datetime import date
from zoneinfo import ZoneInfo

from screen import CATALOG, RULES, Snapshot, decision, eval_rule, instant, is_prescreening, ref

STUDY = "106S01"
MILESTONE_SYSTEM = "urn:pocketmd:research:sotio-milestone"
SPECIMEN_SYSTEM = "http://terminology.hl7.org/CodeSystem/v2-0487"


def cycle_anchor(chart, zone, simulated):
    anchors = {}
    refs = []
    for record in chart.resources.values():
        if (record["resourceType"] != "Observation" or record.get("subject", {}).get("reference") != chart.person
                or record.get("encounter", {}).get("reference") != chart.visit):
            continue
        codes = [c.get("code") for c in record.get("code", {}).get("coding", []) if c.get("system") == MILESTONE_SYSTEM]
        if not codes or record.get("status") in {"cancelled", "entered-in-error"}:
            continue
        if codes not in (["C1D1-actual"], ["C1D1-planned"]):
            raise ValueError("Reconcile conflicting cycle start milestone coding.")
        links = [x.get("reference", "") for x in record.get("derivedFrom", [])]
        doc = chart.resources.get(links[0].split("/_history/")[0]) if len(links) == 1 else None
        if (not doc or doc["resourceType"] != "DocumentReference" or ref(doc) != links[0]
                or doc.get("subject", {}).get("reference") != chart.person or doc.get("status") != "current"
                or instant(doc["date"]) > chart.cutoff or instant(record["issued"]) > chart.cutoff
                or record.get("status") not in {"final", "amended", "corrected"}):
            raise ValueError("Verify the source, date and final status of the clinical cycle start.")
        value = date.fromisoformat(record["valueDateTime"])
        if codes[0] == "C1D1-actual" and value > instant(record["issued"]).astimezone(ZoneInfo(zone)).date():
            raise ValueError("A future cycle start cannot be documented as already administered.")
        anchors.setdefault(codes[0], set()).add(value.isoformat())
        refs.extend([ref(record), ref(doc)])
    if not anchors:
        return simulated, []
    actual = anchors.get("C1D1-actual")
    values = actual or anchors["C1D1-planned"]
    if len(values) != 1:
        raise ValueError("Resolve conflicting C1D1 dates.")
    return {"basis": "documented_actual" if actual else "documented_plan", "cycle_1_day_1": next(iter(values)),
            "timezone": zone}, refs


def serum_chart(chart):
    filtered = copy(chart)
    filtered.resources = dict(chart.resources)
    specimens = {}
    mapping = CATALOG["albumin"]
    for key, obs in chart.resources.items():
        if obs["resourceType"] != "Observation" or not any(
                c.get("system") == mapping["system"] and c.get("code") == mapping["code"]
                for c in obs.get("code", {}).get("coding", [])):
            continue
        link = obs.get("specimen", {}).get("reference", "")
        sample = chart.resources.get(link.split("/_history/")[0])
        if (not sample or sample["resourceType"] != "Specimen" or sample.get("subject", {}).get("reference") != chart.person
                or ("/_history/" in link and ref(sample) != link) or sample.get("status") not in (None, "available")
                or {v.get("code") for v in sample.get("type", {}).get("coding", []) if v.get("system") == SPECIMEN_SYSTEM} != {"SER"}):
            filtered.resources.pop(key)
            continue
        specimens[ref(obs)] = ref(sample)
    return filtered, specimens


def transfusion(chart, cycle):
    rule = RULES[STUDY + "-E04"]
    if not cycle or is_prescreening(chart.encounter):
        return eval_rule(chart, rule, cycle)
    anchor = date.fromisoformat(cycle["cycle_1_day_1"])
    zone = ZoneInfo(cycle["timezone"])
    evidence = list(chart.evidence)
    previous, intervening, covered = None, False, False
    for assessment, event, refs in chart.readings(rule["fact"]):
        evidence.extend(refs)
        if previous is not None and (event is None or event < previous):
            return decision("MISSING_DATA", "Reconcile inconsistent transfusion histories.", evidence)
        previous = event
        days = (anchor - event.astimezone(zone).date()).days if event else None
        if days is not None and 0 < days < rule["days"]:
            intervening = True
        if assessment.astimezone(zone).date() >= anchor and (days is None or days >= rule["days"]):
            covered = True
    if intervening:
        return decision("NOT_MET", "Confirmed red-cell transfusion less than 14 days before C1D1.", evidence)
    if covered:
        return decision("MET", "Documented history covers the pre-cycle window and its exclusive 14-day boundary.", evidence)
    return decision("MISSING_DATA", "Obtain history covering the pre-cycle window or clarify same-day ordering.", evidence)


def corrected_criteria(bundle, patient, encounter, cutoff, zone, simulated):
    keys = ("E04", "I08", "I12", "I15")
    try:
        chart = Snapshot(bundle, patient, STUDY, encounter, cutoff)
        cycle, sources = cycle_anchor(chart, zone, simulated)
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        return {k: decision("MISSING_DATA", "Cannot verify the screening context or C1D1: " + str(exc)) for k in keys}
    results = {}
    for key in keys:
        rule = RULES[STUDY + "-" + key]
        try:
            if key == "E04":
                result = transfusion(chart, cycle)
            elif key == "I12":
                filtered, specimen_refs = serum_chart(chart)
                result = eval_rule(filtered, rule, cycle, zone)
                matched = [specimen_refs[r] for r in result["evidence"] if r in specimen_refs]
                result["evidence"] = sorted(set(result["evidence"] + matched))
                if result["state"] == "MISSING_DATA" and cycle:
                    result["reason"] += " Verify the measured specimen is serum."
            else:
                result = eval_rule(chart, rule, cycle, zone)
            if cycle:
                result["schedule_basis"] = cycle
                result["evidence"] = sorted(set(result["evidence"] + sources))
            results[key] = result
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            results[key] = decision("MISSING_DATA", "Evidence could not be verified: " + str(exc), chart.evidence)
    return results
