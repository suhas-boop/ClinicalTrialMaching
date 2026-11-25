"""Evaluate the DB-1311 v6 baseline triplicate QTcF exclusion on a normalized FHIR R4 snapshot.

Run: python duality_qtc.py --self-test
     python duality_qtc.py --example > example.json
     python duality_qtc.py example.json

The input is {"bundle": {...}, "context":{"patient":"Patient/...", "encounter":"Encounter/...",
"first_dose_ref":"ServiceRequest/.../_history/1", "as_of":"ISO instant", "timezone":"IANA zone"}}.
Local codes below denote synthetic normalization contracts and require site validation.
A local order links the three 12-lead reports. Each report identifies an independent tracing,
the physician review, the preparation attestation, and the Fridericia measurement on that tracing.
Codings and source links must be established during ingestion, never inferred from a display string.
"""
import argparse
import json
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

STUDY = "DB-1311-O-1001"
CRITERION = "E05"
RULES = [CRITERION]
SOURCE = {"study":STUDY, "criterion":CRITERION, "protocol_version":"6.0, 19 April 2024",
          "protocol_sha256":"1c20138b1b1d0cf2e9f071154cfbfeb71d3bc7a5857881810c9a0ece7ba21c67", "locators":["§5.2 item 5, p. 63","§8.2.3, p. 85","§9.1, p. 93"],
          "terminology":["https://loinc.org/76634-5","https://loinc.org/34534-8"],
          "diagnostic_scope":"Synthetic normalized screening snapshot; metadata and local-code normalization require site verification."}
LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"
LOCAL = "urn:pocketmd:synthetic:screening-ecg"
STUDY_SYSTEM = "urn:pocketmd:demo:screening-study"
TRACING_SYSTEM = LOCAL + ":source-tracing"
ROLE_SYSTEM = "urn:pocketmd:demo:study-roles"
FINAL = {"final","amended","corrected","appended"}

class Hold(ValueError):
    """More evidence or agreement is necessary before evaluating the exclusion."""

def need(condition, message):
    if not condition:
        raise Hold(message)

def instant(value):
    need(isinstance(value,str) and "T" in value, "Need an offset-qualified, time-resolved source timestamp.")
    try:
        t = datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError:
        raise Hold("Invalid timestamp in the normalized snapshot.") from None
    need(t.tzinfo is not None, "Need an offset-qualified time for ordering.")
    return t

def ref(resource):
    return f"{resource['resourceType']}/{resource['id']}/_history/{resource['meta']['versionId']}"

def codes(concept,system):
    return {row.get("code") for row in concept.get("coding",[]) if row.get("system")==system}

def reference(value):
    return value.get("reference","") if isinstance(value,dict) else ""

def is_versioned(resource_id):
    parts=resource_id.split("/")
    return len(parts)==4 and parts[2]=="_history" and all(parts)

class Chart:
    def __init__(self,bundle,context):
        self.asof=instant(context.get("as_of"))
        self.patient=context["patient"]
        self.encounter=context["encounter"]
        self.zone=ZoneInfo(context["timezone"])
        self.by_ref={}
        self.logical={}
        need(bundle.get("resourceType")=="Bundle" and bundle.get("type")=="collection",
             "Provide a normalized as-of FHIR collection bundle.")
        for entry in bundle.get("entry",[]):
            r=entry["resource"]
            if instant(r["meta"]["lastUpdated"])>self.asof:
                continue
            need(not r.get("modifierExtension") and not r.get("implicitRules"),"Resolve resource modifiers before interpreting the snapshot.")
            exact=ref(r)
            logical=exact.split("/_history/")[0]
            need(is_versioned(exact) and logical not in self.logical, "Provide one version per logical resource at the selected as-of instant.")
            self.by_ref[exact]=r
            self.logical[logical]=r
        self.refs=[]
        self.get(self.patient,"Patient",pinned=False)
        encounter=self.get(self.encounter,"Encounter",pinned=False)
        scoped_ids={x.get("value") for x in encounter.get("identifier",[]) if x.get("system")==STUDY_SYSTEM}
        need(scoped_ids=={STUDY} and reference(encounter.get("subject"))==self.patient
             and encounter.get("status") in {"in-progress","finished"}, "Verify patient and study screening encounter.")
        self.start=instant(encounter["period"]["start"])
        self.end=min(self.asof,instant(encounter["period"]["end"])) if encounter["period"].get("end") else self.asof
        need(self.start<=self.end,"The screening encounter is outside the snapshot.")
        identity=context["first_dose_ref"]
        if identity.startswith("MedicationAdministration/"):
            anchor=self.get(identity,"MedicationAdministration")
            study_ids={r.get("value") for r in anchor.get("identifier",[]) if r.get("system")==STUDY_SYSTEM}
            event_ids={r.get("value") for r in anchor.get("identifier",[]) if r.get("system")==LOCAL+":event"}
            need(reference(anchor.get("subject"))==self.patient and study_ids=={STUDY} and event_ids=={"c1d1-first-dose"}
                 and anchor.get("status")=="completed"
                 and codes(anchor.get("medicationCodeableConcept",{}),LOCAL)=={"DB-1311"},
                 "Verify actual drug identity, patient, study, C1D1 and completed first dose.")
            self.anchor=instant(anchor.get("effectiveDateTime"))
            need(self.anchor<=self.asof,"The recorded actual first dose cannot be in the future.")
            self.anchor_type="actual"
        else:
            anchor=self.get(identity,"ServiceRequest")
            self.same_patient(anchor)
            need(codes(anchor.get("code",{}),LOCAL)=={"c1d1-first-dose"} and anchor.get("status") in {"active","completed"}
                 and anchor.get("intent")=="order", "Identify a validated, current C1D1 order for this study.")
            need(instant(anchor.get("authoredOn"))<=self.asof,"C1D1 order was unavailable at the as-of instant.")
            self.anchor=instant(anchor.get("occurrenceDateTime"))
            self.anchor_type="planned"


    def same_patient(self,r):
        need(reference(r.get("subject"))==self.patient and reference(r.get("encounter"))==self.encounter,
             "Evidence belongs to another patient or screening encounter.")

    def get(self,identity,kind,pinned=True):
        row=self.by_ref.get(identity) if pinned else self.logical.get(identity)
        need(row is not None and row["resourceType"]==kind,"A required "+kind+" resource has no matching version.")
        self.refs.append(ref(row))
        return row

    def eligible_time(self,t):
        calendar=(self.anchor.astimezone(self.zone).date()-t.astimezone(self.zone).date()).days
        elapsed=self.anchor-t
        if elapsed<=timedelta(0): return False
        # The protocol gives days, without specifying how to classify a discordant calendar/elapsed boundary.
        by_calendar=0<=calendar<=7
        by_duration=elapsed<=timedelta(days=7)
        need(by_calendar==by_duration, "Resolve a boundary where calendar-day and elapsed-time interpretations differ.")
        return self.start<=t<=self.end and by_calendar

    def measurement(self,report):
        self.same_patient(report)
        need(report.get("status") in FINAL and codes(report.get("code",{}),LOINC)=={"34534-8"},
             "Verify final 12-lead ECG report and modality.")
        issued=instant(report.get("issued"))
        t=instant(report.get("effectiveDateTime"))
        need(t<=issued<=self.asof and issued<self.anchor,"Verify acquisition and release times for the ECG report.")
        need(not any(k.startswith("effective") and k!="effectiveDateTime" for k in report),"Resolve ambiguous ECG timing.")
        tracing={i.get("value") for i in report.get("identifier",[]) if i.get("system")==TRACING_SYSTEM}
        need(len(tracing)==1 and all(tracing),"Provide the unique source tracing identity.")
        roles=[self.get(reference(r),"PractitionerRole") for r in report.get("resultsInterpreter",[])]
        def clinician(role):
            identifiers={r.get("value") for r in role.get("identifier",[]) if r.get("system")==LOCAL+":study"}
            qualifications=set().union(*(codes(c,ROLE_SYSTEM) for c in role.get("code",[])))
            period=role.get("period",{})
            person=self.get(reference(role.get("practitioner")), "Practitioner")
            need(person.get("active") is True and bool(person.get("identifier") or person.get("name")), "Identify the reviewing physician.")
            return (identifiers=={STUDY} and bool(qualifications & {"investigator","designated-physician","qualified-physician"})
                    and role.get("active") is True and instant(period.get("start"))<=issued
                    and (not period.get("end") or issued<=instant(period["end"])))
        need(any(clinician(r) for r in roles),"Supply the study-authorized physician's review of the ECG.")
        qt=[]; preparation=[]
        for link in report.get("result",[]):
            ob=self.get(reference(link),"Observation")
            self.same_patient(ob)
            if codes(ob.get("code",{}),LOINC)=={"76634-5"}: qt.append(ob)
            if codes(ob.get("code",{}),LOCAL)=={"tracing-preparation"}: preparation.append(ob)
        need(len(qt)==1 and len(preparation)==1,"Each ECG needs one explicit Fridericia measurement and one preparation assessment.")
        measure,prep=qt[0],preparation[0]
        if "method" in measure:
            need(codes(measure["method"],LOCAL)=={"fridericia"}, "Reconcile the populated method with the Fridericia-specific code.")
        for ob in (measure,prep):
            need(ob.get("status") in {"final","amended","corrected"} and not ob.get("dataAbsentReason")
                 and instant(ob.get("effectiveDateTime"))==t and t<=instant(ob.get("issued"))<=issued,
                 "Verify recorded preparation, measurement status, release and tracing time.")
            need(not any(k.startswith("effective") and k!="effectiveDateTime" for k in ob),"Resolve conflicting observation timing.")
            links=ob.get("derivedFrom",[])
            need(len(links)==1,"Link each measurement and preparation to its versioned tracing source.")
            doc=self.get(reference(links[0]),"DocumentReference")
            need(reference(doc.get("subject"))==self.patient and doc.get("status")=="current"
                 and instant(doc.get("date"))<=issued,"Verify the tracing source and its patient.")
        need(reference(measure["derivedFrom"][0])==reference(prep["derivedFrom"][0]),"The preparation and result must reference the same tracing.")
        need({k for k in prep if k.startswith("value")}=={"valueCodeableConcept"}
             and codes(prep.get("valueCodeableConcept",{}),LOCAL) in ({"supine-after-approx-5-min"},{"semi-recumbent-after-approx-5-min"}),
             "A source-backed attestation of the protocol posture and approximately five-minute rest is needed.")
        need({k for k in measure if k.startswith("value")}=={"valueQuantity"},"An exact QTcF quantity is required.")
        quantity=measure["valueQuantity"]
        need(quantity.get("system")==UCUM and quantity.get("code") in {"ms","s"} and "comparator" not in quantity
             and type(quantity.get("value")) in (int,float,Decimal), "Use an exact, numeric QTcF measurement in UCUM ms or s.")
        v=Decimal(str(quantity["value"]))
        need(v.is_finite() and v>0,"Invalid QTcF interval.")
        return t, v*(1000 if quantity["code"]=="s" else 1), tracing.pop(), ref(measure), reference(measure["derivedFrom"][0])

    def group(self,order,reports):
        self.refs.append(ref(order))
        need(order.get("status") in {"active","completed"} and order.get("intent")=="order"
             and instant(order.get("authoredOn"))<=self.asof,
             "Confirm an authorized screening triplicate order.")
        need(len(reports)==3, "Supply exactly three distinct reports for a single ordered screening triplet.")
        for r in reports:
            need([reference(k) for k in r.get("basedOn",[])]==[ref(order)],"The tracing must belong unambiguously to one ordered triplet.")
            self.refs.append(ref(r))
        values=[self.measurement(r) for r in reports]
        for col in (2,3,4):
            need(len({v[col] for v in values})==3,"Copied readings or source tracings cannot stand in for three acquisitions.")
        times=sorted(v[0] for v in values)
        need(times[-1]-times[0]<=timedelta(minutes=10),"Tracings exceed the 10-minute group window.")
        need(all(self.eligible_time(t) for t in times),"All three acquisitions must precede first dosing within the protocol screening window.")
        total=sum(v[1] for v in values)
        return {"order":ref(order),"measurements":[{"at":v[0].isoformat(),"ms":str(v[1]),"source":v[4],"observation":v[3]} for v in values],
                "mean_ms":str(total/3),"state":"NOT_MET" if total>3*470 else "MET"}

def evaluate(bundle,context):
    chart=None; packs=[]
    try:
        chart=Chart(bundle,context)
        orders=[r for r in chart.logical.values() if r["resourceType"]=="ServiceRequest"
                and codes(r.get("code",{}),LOCAL)=={"baseline-triplicate-ecg"} and reference(r.get("subject"))==chart.patient
                and reference(r.get("encounter"))==chart.encounter and r.get("status") not in {"revoked","entered-in-error"}]
        need(orders,"No study screening triplicate order was established.")
        for order in orders:
            reports=[r for r in chart.logical.values() if r['resourceType']=='DiagnosticReport'
                     and ref(order) in [reference(v) for v in r.get("basedOn",[])]
                     and r.get("status") not in {"cancelled","entered-in-error"}]
            if reports and all(not chart.eligible_time(instant(r.get("effectiveDateTime"))) for r in reports):
                continue
            packs.append(chart.group(order,reports))
        need(packs,"No complete screening triplet within seven days before the first dose.")
        states={p["state"] for p in packs}
        need(len(states)==1,"Qualifying triplets disagree across the exclusion threshold. Resolve which triplet governs.")
        state=states.pop()
        reason="The complete ordered triplet mean exceeds 470 ms." if state=="NOT_MET" else "The complete ordered triplet mean does not exceed 470 ms."
    except (Hold,KeyError,TypeError,ValueError,AttributeError,InvalidOperation,ZoneInfoNotFoundError) as exc:
        state,reason='MISSING_DATA',str(exc)
    return {"criterion":CRITERION,"state":state,"reason":reason,"evidence":sorted(set(chart.refs)) if chart else [],
            "groups":packs,"as_of":context.get("as_of"),"first_dose_ref":context.get("first_dose_ref"),
            "first_dose_time":chart.anchor.isoformat() if chart else None,"anchor_type":chart.anchor_type if chart else None,"provenance":SOURCE}
def _coding(system,code):
    return {"coding":[{"system":system,"code":code}]}

def _link(s):
    return {"reference":s}

def example(groups=((460,470,480),)):
    """Generate a research fixture. No patient data or commercial protocol file is embedded."""
    t0="2026-05-01T07:00:00Z"; anchor="2026-05-07T10:00:00Z"
    context={"patient":"Patient/demo","encounter":"Encounter/screen",
             "first_dose_ref":"ServiceRequest/first/_history/1","as_of":"2026-05-06T20:00:00Z","timezone":"UTC"}
    resources=[]
    def add(kind,id,stamp=t0,**fields):
        r={"resourceType":kind,"id":id,"meta":{"versionId":"1","lastUpdated":stamp},**fields}
        resources.append(r);return ref(r)
    subject,encounter=_link(context['patient']),_link(context['encounter'])
    add('Patient','demo')
    add('Encounter','screen',status='in-progress',subject=subject,period={'start':t0},
        identifier=[{'system':STUDY_SYSTEM,'value':STUDY}])
    add('ServiceRequest','first',subject=subject,encounter=encounter,intent='order',status='active',
        code=_coding(LOCAL,'c1d1-first-dose'),authoredOn=t0,occurrenceDateTime=anchor)
    clinician=add('Practitioner','reviewer-physician',active=True,identifier=[{'system':LOCAL+':staff','value':'demo-physician'}])
    role=add('PractitionerRole','reviewer',practitioner=_link(clinician),active=True,code=[_coding(ROLE_SYSTEM,'designated-physician')],
             period={'start':t0},identifier=[{'system':LOCAL+':study','value':STUDY}])
    for j,vals in enumerate(groups):
        order=add('ServiceRequest',f'group-{j}',subject=subject,encounter=encounter,authoredOn=t0,
                  status='completed',intent='order',code=_coding(LOCAL,'baseline-triplicate-ecg'))
        for i,val in enumerate(vals):
            t=f'2026-05-03T{10+j:02d}:{3*i:02d}:00Z'
            issued=f'2026-05-03T{11+j:02d}:00:00Z'
            doc=add('DocumentReference',f'tracing-{j}-{i}',issued,subject=subject,status='current',date=t,
                    content=[{'attachment':{'contentType':'application/pdf','title':'Synthetic source tracing'}}])
            shared=dict(status='final',subject=subject,encounter=encounter,effectiveDateTime=t,issued=issued,derivedFrom=[_link(doc)])
            measure=add('Observation',f'qtcf-{j}-{i}',issued,**shared,code=_coding(LOINC,'76634-5'),
                        valueQuantity={'system':UCUM,'code':'ms','value':val})
            prep=add('Observation',f'prep-{j}-{i}',issued,**shared,code=_coding(LOCAL,'tracing-preparation'),
                     valueCodeableConcept=_coding(LOCAL,'supine-after-approx-5-min'))
            add('DiagnosticReport',f'ecg-{j}-{i}',issued,status='final',effectiveDateTime=t,issued=issued,subject=subject,
                encounter=encounter,basedOn=[_link(order)],code=_coding(LOINC,'34534-8'),resultsInterpreter=[_link(role)],
                identifier=[{'system':TRACING_SYSTEM,'value':f'SYNTHETIC-{j}-{i}'}],result=[_link(measure),_link(prep)])
    return {'bundle':{'resourceType':'Bundle','type':'collection','entry':[{'resource':r} for r in resources]},'context':context}

def _item(payload,id):
    return next(e['resource'] for e in payload['bundle']['entry'] if e['resource']['id']==id)

def run_checks():
    cases=[]
    def run(label,expected,payload=None,change=None):
        p=example() if payload is None else payload
        if change:change(p)
        result=evaluate(p['bundle'],p['context'])
        cases.append({'criterion':CRITERION,'case':label,'expected':expected,'actual':result['state']})
    run('Equality at 470 passes the exclusion', 'MET')
    run('Mean above 470 crosses boundary','NOT_MET',example(((460,470,480.01),)))
    run('One high tracing with mean below threshold','MET',example(((440,450,500),)))
    run('Two readings only','MISSING_DATA',example(((420,440),)))
    run('Different valid packs disagree','MISSING_DATA',example(((450,460,470),(460,480,495))))
    run('Agreeing independent packs','NOT_MET',example(((471,472,473),(490,480,495))))
    run('Bazett instead of Fridericia','MISSING_DATA',change=lambda p:_item(p,'qtcf-0-0').update(code=_coding(LOINC,'76635-2')))
    run('Generic QTc cannot establish correction','MISSING_DATA',change=lambda p:_item(p,'qtcf-0-0').update(code=_coding(LOINC,'8636-3')))
    run('Contradictory populated correction method','MISSING_DATA',change=lambda p:_item(p,'qtcf-0-0').update(method=_coding(LOCAL,'bazett')))
    run('12-lead identity missing','MISSING_DATA',change=lambda p:_item(p,'ecg-0-0').update(code=_coding(LOCAL,'ecg')))
    run('Duplicated source tracing ID','MISSING_DATA',change=lambda p:_item(p,'ecg-0-1').update(identifier=_item(p,'ecg-0-0')['identifier']))
    run('Duplicated tracing document','MISSING_DATA',change=lambda p:[_item(p,s+'-0-1').update(derivedFrom=_item(p,s+'-0-0')['derivedFrom']) for s in ['prep','qtcf']])
    run('Incompatible patient','MISSING_DATA',change=lambda p:_item(p,'qtcf-0-1').update(subject=_link('Patient/other')))
    run('Wrong encounter / order membership','MISSING_DATA',change=lambda p:_item(p,'ecg-0-1').update(basedOn=[_link('ServiceRequest/other/_history/1')]))
    run('Source version missing','MISSING_DATA',change=lambda p:_item(p,'qtcf-0-1').update(derivedFrom=[_link('DocumentReference/tracing-0-1/_history/99')]))
    run('Unsigned ECG interpretation','MISSING_DATA',change=lambda p:_item(p,'ecg-0-0').update(resultsInterpreter=[]))
    run('Physician no longer authorized at issue','MISSING_DATA',change=lambda p:_item(p,'reviewer')['period'].update(end='2026-05-03T09:00:00Z'))
    run('Unverified preparation','MISSING_DATA',change=lambda p:_item(p,'prep-0-1').update(valueCodeableConcept=_coding(LOCAL,'unknown')))
    run('Convertible UCUM seconds','MET',change=lambda p:_item(p,'qtcf-0-1')['valueQuantity'].update(value=0.47,code='s'))
    run('Incompatible measurement unit','MISSING_DATA',change=lambda p:_item(p,'qtcf-0-1')['valueQuantity'].update(code='Hz'))
    run('Censored quantity','MISSING_DATA',change=lambda p:_item(p,'qtcf-0-1')['valueQuantity'].update(comparator='<'))
    run('Different as-of scope','MISSING_DATA',change=lambda p:p['context'].update(as_of='2026-05-02T20:00:00Z'))
    run('More than seven days before anchor','MISSING_DATA',change=lambda p:_item(p,'first').update(occurrenceDateTime='2026-05-11T10:00:00Z'))
    run('Same-day before dose permitted','MET',change=lambda p:_item(p,'first').update(occurrenceDateTime='2026-05-03T14:00:00Z'))
    run('Dose time falls within the triplet','MISSING_DATA',change=lambda p:_item(p,'first').update(occurrenceDateTime='2026-05-03T10:04:00Z'))
    run('One resulting timestamp has only date','MISSING_DATA',change=lambda p:_item(p,'ecg-0-0').update(effectiveDateTime='2026-05-03'))
    def retime(p,mm):
        v=f'2026-05-03T10:{mm}:00Z'
        for key in ['ecg-0-2','qtcf-0-2','prep-0-2']:
            _item(p,key)['effectiveDateTime']=v
        _item(p,'tracing-0-2')['date']=v
    run('Exactly ten minutes apart','MET',change=lambda p:retime(p,'10'))
    run('Eleven minutes apart','MISSING_DATA',change=lambda p:retime(p,'11'))
    def actual(p):
        anchor="2026-05-05T11:00:00Z"
        m={"resourceType":"MedicationAdministration","id":"admin","meta":{"versionId":"1","lastUpdated":anchor},
           "subject":_link("Patient/demo"),"status":"completed","medicationCodeableConcept":_coding(LOCAL,"DB-1311"),
           "identifier":[{"system":STUDY_SYSTEM,"value":STUDY},{"system":LOCAL+":event","value":"c1d1-first-dose"}],
           "effectiveDateTime":anchor}
        p["bundle"]["entry"].append({"resource":m})
        p["context"]["first_dose_ref"]=ref(m)
    run("Actual first dose re-evaluation", "MET",change=actual)
    run("Resolved report arrives after C1D1", "MISSING_DATA",change=lambda p:_item(p,'first').update(occurrenceDateTime='2026-05-03T10:30:00Z'))
    run("Named interpreter cannot be identified", "MISSING_DATA",change=lambda p:_item(p,"reviewer").pop("practitioner"))
    return cases

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input',nargs='?',type=Path)
    ap.add_argument('--example',action='store_true')
    ap.add_argument('--self-test',action='store_true')
    args=ap.parse_args()
    if args.self_test:
        rows=run_checks();print(json.dumps(rows,indent=2));raise SystemExit(int(any(r['expected']!=r['actual'] for r in rows)))
    if args.example:
        print(json.dumps(example(),indent=2));raise SystemExit
    if args.input is None:
        ap.error('Supply an input JSON or use --example or --self-test.')
    p=json.loads(args.input.read_text(),parse_float=Decimal)
    print(json.dumps(evaluate(p['bundle'],p['context']),indent=2))
