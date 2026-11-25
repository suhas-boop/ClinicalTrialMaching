"""Source-scoped scalar research rules on synthetic FHIR R4 Collection bundles.
Clinical milestone Observations use a research-only, study-qualified event code system.
A missing, conflicting, or insufficiently precise input never establishes a pass.
"""
import argparse
import json
import math
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"
EVENT = "urn:pocketmd:research:study-event:"
METHOD = "urn:pocketmd:research:imaging-method"
RULES = {
    ("1479-0032", "I12"): ("ecog", "randomization", 28, "calendar_prior", "latest"),
    ("FOG-001-301", "DB-I07"): ("ecog", "randomization", 28, "fog_screen", "agreement"),
    ("DB-1311-O-1001", "I05"): ("ecog", "C1D1", 7, "before", "agreement"),
    ("DB-1311-O-1001", "I06"): ("lvef", "enrollment", 28, "before", "agreement"),
}
VERSIONS = {"1479-0032":"2.0", "DB-1311-O-1001":"6.0", "FOG-001-301":"1.0"}

def event_system(study):
    return EVENT + study + ":" + VERSIONS[study]

CODES = {"ecog":"89247-1", "lvef":"10230-1"}


def moment(value):
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("Supply an offset-qualified clinical event time.")
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("Supply a timezone for the clinical event.")
    return t


def versioned(r):
    return r["resourceType"] + "/" + r["id"] + "/_history/" + r["meta"]["versionId"]


def codes(c, system):
    return {x.get("code") for x in c.get("coding", []) if x.get("system") == system}


def measurement(obs, fact):
    value_keys = {k for k in obs if k.startswith("value")}
    if "dataAbsentReason" in obs:
        raise ValueError("The selected observation has no documented result.")
    if fact == "ecog":
        val = obs.get("valueInteger")
        if value_keys != {"valueInteger"} or type(val) is not int or not 0 <= val <= 5:
            raise ValueError("Verify the recorded ECOG grade and its instrument.")
        return val
    if codes(obs.get("method", {}), METHOD) not in ({"ECHO"},{"MUGA"}):
        raise ValueError("Verify echocardiography or MUGA as the measurement method.")
    q = obs.get("valueQuantity", {})
    if value_keys != {"valueQuantity"} or q.get("system") != UCUM or q.get("code") != "%" or "comparator" in q:
        raise ValueError("Verify the LVEF percentage and unit.")
    val = q.get("value")
    if type(val) not in (float, int) or not math.isfinite(val) or not 0 <= val <= 100:
        raise ValueError("Verify the measured ejection fraction.")
    return Decimal(str(val))


def evaluate(study, criterion, bundle, patient, as_of, site_zone):
    if (study, criterion) not in RULES:
        raise ValueError("No released scalar rule for this study/criterion.")
    fact, anchor, days, kind, aggregation = RULES[study, criterion]
    refs = set()
    def outcome(state, reason):
        return dict(study=study, version=VERSIONS[study], criterion=criterion, state=state, reason=reason, evidence=sorted(refs))
    try:
        asof, zone = moment(as_of), ZoneInfo(site_zone)
        if bundle.get("type") != "collection" or bundle.get("resourceType") != "Bundle":
            raise ValueError("Supply an as-of FHIR Collection Bundle.")
        resources = {}
        for entry in bundle["entry"]:
            r = entry["resource"]
            if moment(r["meta"]["lastUpdated"]) > asof:
                continue
            k = r["resourceType"] + "/" + r["id"]
            if k in resources or not r["meta"].get("versionId") or r.get("modifierExtension") or r.get("implicitRules"):
                raise ValueError("Supply a single interpretable resource version for the snapshot.")
            resources[k] = r
        subj = "Patient/" + patient
        refs.add(versioned(resources[subj]))
        observations = [r for r in resources.values() if r["resourceType"] == "Observation" and
                        r.get("subject", {}).get("reference") == subj and r.get("status") not in {"cancelled","entered-in-error"}]

        def proof(r, cutoff=None):
            cutoff = asof if cutoff is None else cutoff
            dr = r.get("derivedFrom", [])
            if not dr:
                raise ValueError("A versioned source document is required.")
            evidence = {versioned(r)}
            for link in dr:
                ref = link["reference"]
                doc = resources.get(ref.split("/_history/")[0])
                if (not doc or doc["resourceType"] != "DocumentReference" or versioned(doc) != ref
                        or doc.get("subject", {}).get("reference") != subj or doc.get("status") != "current"
                        or moment(doc["date"]) > cutoff or moment(doc["meta"]["lastUpdated"]) > cutoff):
                    raise ValueError("Verify the source document, patient, version and availability.")
                evidence.add(ref)
            return evidence

        def time_of(r):
            if {k for k in r if k.startswith("effective")} != {"effectiveDateTime"}:
                raise ValueError("Confirm measurement time and precision.")
            t = moment(r["effectiveDateTime"])
            if t > moment(r["issued"]) or moment(r["issued"]) > asof:
                raise ValueError("The evidence was unavailable at the evaluation time.")
            return t

        def milestone(name):
            times = set()
            for obs in observations:
                spec_codes = codes(obs.get("code", {}), event_system(study))
                if name not in spec_codes or moment(obs["issued"]) > asof:
                    continue
                if (spec_codes != {name} or obs.get("status") not in ("final","corrected","amended")
                        or obs.get("valueBoolean") is not True
                        or {k for k in obs if k.startswith("value")} != {"valueBoolean"} or "dataAbsentReason" in obs):
                    raise ValueError("Verify the study milestone: " + name)
                times.add(time_of(obs))
                refs.update(proof(obs))
            if len(times) != 1:
                raise ValueError("A unique, source-linked study milestone is required: " + name)
            return times.pop()

        reference = milestone(anchor)
        if kind == "fog_screen":
            c1 = milestone("C1D1")
            consent = milestone("consent")
            if not consent <= reference <= c1:
                raise ValueError("Verify consent, randomization and treatment chronology.")
        eligible = []
        for obs in observations:
            obs_codes = codes(obs.get("code", {}), LOINC)
            if (CODES[fact] not in obs_codes or moment(obs["issued"]) > reference
                    or moment(obs["meta"]["lastUpdated"]) > reference):
                continue
            t = time_of(obs)
            date_diff = (reference.astimezone(zone).date()-t.astimezone(zone).date()).days
            age = reference - t
            if kind == "calendar_prior":
                if not 1 <= date_diff <= days:
                    continue
            elif kind == "before":
                if t >= reference or (date_diff > days and age > timedelta(days=days)):
                    continue
                if (date_diff<=days) != (age<=timedelta(days=days)):
                    raise ValueError("Clarify the day boundary when elapsed and calendar interpretations disagree.")
            else:
                if t >= reference:
                    continue
                preconsent = t < consent
                anchor_days = (c1.astimezone(zone).date()-t.astimezone(zone).date()).days
                if preconsent:
                    if date_diff > days and age > timedelta(days=days):
                        continue
                    if (date_diff<=days) != (age<=timedelta(days=days)):
                        raise ValueError("Confirm timing for the pre-consent routine assessment.")
                    if "routine-care" not in codes(obs.get("category",[{}])[0],event_system(study)):
                        raise ValueError("Verify pre-consent assessment as permitted routine care.")
                elif not 1<=anchor_days<=28:
                    continue
            if obs_codes != {CODES[fact]} or obs.get("status") not in ("final","amended","corrected"):
                raise ValueError("Confirm the instrument, final status and conflicting codes.")
            eligible.append((t, measurement(obs, fact), proof(obs, reference)))
        if not eligible:
            return outcome("MISSING_DATA","Obtain a qualifying dated screening " + fact.upper() + " result.")
        if aggregation == "latest":
            last = max(t for t,_,_ in eligible)
            eligible = [row for row in eligible if row[0]==last]
        for _,_,r in eligible:
            refs.update(r)
        passes = {v in (0,1) if fact=="ecog" else v >= 50 for _,v,_ in eligible}
        if len(passes) != 1:
            return outcome("MISSING_DATA","Resolve decision-changing discordance across qualifying observations.")
        return outcome("MET" if passes.pop() else "NOT_MET","Qualified screening evidence compared with the source threshold.")
    except (KeyError, ValueError, TypeError, AttributeError, IndexError, ZoneInfoNotFoundError, OverflowError) as e:
        return outcome("MISSING_DATA",str(e))


def example(study, criterion, good=True):
    fact, anchor, *_ = RULES[study,criterion]
    day = datetime(2025,2,28,12,tzinfo=timezone.utc)
    def res(kind, ident, **fields):
        return {"resourceType":kind,"id":ident,"meta":{"versionId":"1","lastUpdated":day.isoformat()},**fields}
    patient = res("Patient","synthetic")
    subj={"reference":"Patient/synthetic"}
    items=[patient]
    def obs(ident,system,code,t,fields):
        doc=res("DocumentReference","report-"+ident,subject=subj,status="current",date=t.isoformat(),content=[{"attachment":{"title":"Synthetic verified report"}}])
        o=res("Observation",ident,status="final",subject=subj,code={"coding":[{"system":system,"code":code}]},effectiveDateTime=t.isoformat(),issued=t.isoformat(),derivedFrom=[{"reference":versioned(doc)}],**fields)
        items.extend([doc,o]);return o
    obs("anchor", event_system(study), anchor,day,{"valueBoolean":True})
    if study=="FOG-001-301":
        obs("consent",event_system(study),"consent",day-timedelta(days=7),{"valueBoolean":True})
        obs("treatment",event_system(study),"C1D1",day+timedelta(days=1),{"valueBoolean":True})
    fields=({"valueInteger":1 if good else 2} if fact=="ecog" else
            {"valueQuantity":{"value":50 if good else 49.9,"system":UCUM,"code":"%"},"method":{"coding":[{"system":METHOD,"code":"ECHO"}]}})
    obs("measure",LOINC,CODES[fact],day-timedelta(days=2),fields)
    return {"resourceType":"Bundle","type":"collection","entry":[{"resource":r} for r in items]}


def run_checks():
    results=[]
    for s,k in RULES:
        def check(label,b,want):
            got=evaluate(s,k,b,"synthetic","2025-03-05T12:00:00Z","UTC")
            assert got["state"]==want,(s,k,label,got)
            if want in ("MET","NOT_MET"):
                assert "DocumentReference/report-measure/_history/1" in got['evidence']
            results.append(dict(study=s,criterion=k,case=label,expected=want,actual=got['state']))
        check("inclusive pass",example(s,k),"MET")
        check("outside qualifying score",example(s,k,False),"NOT_MET")
        for label,edit in [
          ("different patient",{"subject":{"reference":"Patient/other"}}),
          ("outside window",{"effectiveDateTime":"2024-10-01T00:00:00Z"}),
          ("missing source",{"derivedFrom":[]}),
          ("imprecise date",{"effectiveDateTime":"2025-02-25"}),
          ("reported after cutoff milestone",{"issued":"2025-03-01T14:00:00Z"}),
          ("preliminary result",{"status":"preliminary"})]:
            b=example(s,k);b['entry'][-1]['resource'].update(edit);check(label,b,"MISSING_DATA")
        b=example(s,k);b['entry'][2]['resource']['code']['coding'][0]['system']=EVENT+"other"
        check("milestone for wrong study",b,"MISSING_DATA")
        b=example(s,k);r=deepcopy(example(s,k,False)['entry'][-1]);r['resource']['id']='other-result';b['entry'].append(r)
        check("conflicting same-time values",b,"MISSING_DATA")
        if k=='I06':
            b=example(s,k);b['entry'][-1]['resource'].pop('method')
            check('unspecified LVEF method',b,'MISSING_DATA')
    return results


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study');parser.add_argument('--criterion');parser.add_argument('--bundle',type=Path)
    parser.add_argument('--patient');parser.add_argument('--as-of');parser.add_argument('--site-zone')
    parser.add_argument('--example',action='store_true');parser.add_argument('--test',action='store_true')
    args=parser.parse_args()
    if args.test: output=run_checks()
    elif args.example: output=example(args.study,args.criterion)
    else: output=evaluate(args.study,args.criterion,json.loads(args.bundle.read_text()),args.patient,args.as_of,args.site_zone)
    print(json.dumps(output,indent=2))
