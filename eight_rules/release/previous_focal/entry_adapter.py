"""Source-linked native R4 adapters for SOTIO I01 and the osteosarcoma part of I17.

The signed prescreen ICF uses a pinned research form and verified detached Ed25519
signature over the consent and its versioned document. Trust enrollment, site
timezone and index malignancy come from an independently trusted context.
I17 recognizes only the two exact osteosarcoma representations below. Sources:
https://bioportal.bioontology.org/ontologies/NCIT?conceptid=C9145&p=classes
https://seer.cancer.gov/tools/solidtumor/current/STM_Combined.pdf (9180/3).
No eligibility or hospital code equivalence is inferred from free text.
"""
import base64
from copy import deepcopy
from datetime import date, datetime, timedelta
from hashlib import sha256
import math
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

import normalized as n

LOINC = "http://loinc.org"
FORM = "urn:pocketmd:research:sotio:consent-form"
PRESCREEN = "prescreen-informed-consent"
VISIT = "urn:pocketmd:research:sotio:consent-attempt"
SIGN_FORMAT = "application/pocketmd-prescreen-ed25519"
VERIFY_STATUS = "http://terminology.hl7.org/CodeSystem/condition-ver-status"
NCIT = "http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl"
ICDO = "http://terminology.hl7.org/CodeSystem/icd-o-3"
OSTEO = {(NCIT, "C9145"), (ICDO, "9180/3")}
V2_REPORT = "http://terminology.hl7.org/CodeSystem/v2-0074"

def reference(r):
    return {"reference": n.ref(r)}

def clean(r):
    return not r.get("modifierExtension") and not r.get("implicitRules")

def codes(concept):
    return {(c.get("system"), c.get("code")) for c in concept.get("coding", []) if isinstance(c,dict)}

def check(condition, message):
    if not condition:
        raise ValueError(message)

def current(snapshot, resource_ref, kind):
    v=resource_ref.get("reference")
    r=snapshot.exact[v]
    check(r["resourceType"]==kind and snapshot.current.get(v.split("/_history/")[0])==r and clean(r),
          "Resource reference must identify a current, exact source version.")
    return r

def ready(value, refs, why):
    return value, None, sorted({n.ref(r) for r in refs}), why

def missing(message):
    return None, "MISSING_DATA", [], message

def b64(data):
    return base64.b64encode(data).decode('ascii')

def signing_payload(consent,doc,signed,who):
    return n.canonical({"purpose":PRESCREEN, "protocol":n.HASH, "when":signed, "who":who,
                        "consent":consent, "source":doc})

def full_date(value):
    check(isinstance(value,str) and len(value)==10, "Full birth date required.")
    return date.fromisoformat(value)

def completed_age(dob, day):
    check(dob<=day,"Birth after consent.")
    return day.year-dob.year-((day.month,day.day)<(dob.month,dob.day))

def consent_date(snap, context, consent):
    study_tag="106S01|"+n.HASH+"|prescreen"
    check(consent["status"]=="active" and clean(consent) and n.tag(consent,n.STUDY,study_tag)
          and n.tag(consent,VISIT,snap.encounter),"Consent is not active for the selected trial attempt.")
    doc=current(snap,consent["sourceReference"],"DocumentReference")
    check(doc["status"]=="current" and doc.get("docStatus") in ("final","amended")
          and doc["subject"]["reference"]==snap.patient and n.tag(doc,n.SOURCE,n.HASH)
          and snap.encounter in {v["reference"] for v in doc.get("context",{}).get("encounter",[])}
          and n.instant(doc["date"])<=snap.at and n.instant(consent["dateTime"])<=snap.at,
          "Consent source, document type or encounter mismatch.")
    check(any(x.get("attachment",{}).get("data") for x in doc["content"]),
          "The signed source must include its verified content.")
    check(any((FORM,PRESCREEN) in codes(cat) for cat in consent["category"]) and
          (FORM,PRESCREEN) in codes(doc["type"]),"Main consent cannot substitute for prescreen.")
    zone=ZoneInfo(context["site_zone"])
    target=n.ref(consent)
    proofs=[r for r in snap.current.values() if r["resourceType"]=="Provenance" and
            any(v.get("reference")==target for v in r.get("target",[]))]
    check(proofs,"Missing consent-signature provenance.")
    accepted=[]
    patient=snap.current[snap.patient]
    check(clean(patient) and clean(snap.current[snap.encounter]) and
          snap.current[snap.encounter].get("status") in ("in-progress","finished"),
          "Verify the patient and study encounter.")
    birth=full_date(patient["birthDate"])
    for p in proofs:
        if not clean(p) or n.instant(p["recorded"])>snap.at:
            continue
        for sig in p.get("signature",[]):
            if sig.get("sigFormat")!=SIGN_FORMAT:
                continue
            who=sig["who"]["reference"]; when=sig["when"]; stamp=n.instant(when)
            check(stamp<=n.instant(consent["dateTime"]) and stamp<=n.instant(p["recorded"]),
                  "Signature postdates consent recording or statement provenance.")
            day=stamp.astimezone(zone).date()
            reg=context.get("prescreen_signers",{}).get(who,{})
            check(reg.get("patient")==snap.patient and reg.get("protocol")==n.HASH and
                  n.instant(reg["from"])<=stamp<=n.instant(reg["through"]),
                  "Signer registration is not valid for the subject, study and signature time.")
            actors={a["who"]["reference"] for a in p["agent"]}
            check(who in actors, "Signer not named in provenance.")
            if who==snap.patient:
                check(reg.get("role")=="participant","Participant identity mismatch.")
                check(completed_age(birth,day)>=18,"Minor requires authorized written representative consent.")
            else:
                check(reg.get("role")=="legal_representative" and who.startswith("RelatedPerson/"),
                      "Authorized legal-representative evidence required.")
                representative=current(snap,{"reference":reg["authority_record"]},"RelatedPerson")
                check(who=="RelatedPerson/"+representative["id"] and representative.get("active") is True
                      and representative["patient"]["reference"]==snap.patient,"Representative identity mismatch.")
                check(completed_age(birth,day)<18,"Adult prescreen requires participant consent.")
            data=base64.b64decode(sig["data"],validate=True)
            pk=Ed25519PublicKey.from_public_bytes(base64.b64decode(reg["public_key"],validate=True))
            pk.verify(data,signing_payload(consent,doc,when,who))
            refs=[p,doc,consent,patient,snap.current[snap.encounter]]
            if who!=snap.patient:refs.append(representative)
            accepted.append((day,refs))
    check(accepted and len({d for d,_ in accepted})==1,"No unique verified prescreen signature date.")
    return accepted[0][0],[r for _,refs in accepted for r in refs]

def weight_sources(snap, context, day, base):
    zone=ZoneInfo(context["site_zone"])
    rows=[]
    for obs in snap.current.values():
        if (obs["resourceType"]!="Observation" or obs.get("subject",{}).get("reference")!=snap.patient
            or (LOINC,"29463-7") not in codes(obs.get("code",{})) or
            obs.get("encounter",{}).get("reference")!=snap.encounter):
            continue
        if obs.get("status") in ("cancelled","entered-in-error","registered","preliminary"):
            continue
        check(obs.get("status") in ("final","amended","corrected") and clean(obs),
              "Verify the weight status and measurement modifiers.")
        value=obs["effectiveDateTime"]
        if len(value)==10:
            event_day=full_date(value)
            check(n.instant(obs["issued"]).astimezone(zone).date()>=event_day,"Issue precedes measurement date.")
            check(event_day<snap.at.astimezone(zone).date(), "Day-precision same-day weight lacks an as-of time.")
        else:
            ts=n.instant(value)
            check(ts<=snap.at and ts<=n.instant(obs["issued"]),"Weight unavailable by cutoff.")
            event_day=ts.astimezone(zone).date()
        if event_day!=day:continue
        check(n.instant(obs["issued"])<=snap.at, "Weight not yet available.")
        check([k for k in obs if k.startswith('value')]==['valueQuantity'],"One numeric weight is required.")
        q=obs["valueQuantity"]; v=q["value"]
        check((q.get("system"),q.get("code"))==(n.UCUM,"kg") and q.get("comparator") is None
              and type(v) in (int,float) and math.isfinite(v) and v>0,"Require measured UCUM kilograms.")
        docs=[]
        allowed=set(snap.registry.get("record",[]))
        for source in obs["derivedFrom"]:
            doc=current(snap,source,"DocumentReference")
            check(doc.get("status")=="current" and doc.get("docStatus") in ("final","amended")
                and doc.get("subject",{}).get("reference")==snap.patient and n.tag(doc,n.SOURCE,n.HASH)
                and n.instant(doc["date"])<=snap.at
                and allowed & {v["reference"] for v in doc["author"]} & {v["reference"] for v in obs["performer"]},
                "Weight source and performer must be verified for this subject.")
            docs.append(doc)
        check(docs,"Missing source for measured weight.")
        rows.append((v,[obs]+docs))
    if not rows:return None
    check(len({v for v,_ in rows})==1,"Conflicting same-day weight measurements.")
    return ready(rows[0][0],base+[r for _,src in rows for r in src],"Measured body weight on the prescreen consent calendar day.")

def pathology(snap,context):
    selected=context.get("index_condition")
    if not selected:return None
    cond=current(snap,{"reference":selected},"Condition")
    check(cond["subject"]["reference"]==snap.patient and (VERIFY_STATUS,"confirmed") in codes(cond["verificationStatus"]),"Index diagnosis is unconfirmed or for another patient.")
    check(snap.episode is not None and n.ref(cond).split("/_history/")[0]==snap.episode,
          "Select the same index malignancy as the matching episode.")
    def matches_osteo(concept):
        representations=codes(concept)
        standard={c for c in representations if c[0] in {NCIT, ICDO}}
        if not standard & OSTEO:
            return False
        check(standard<=OSTEO, "Conflicting histology codes on a single concept.")
        return True
    if not matches_osteo(cond["code"]):return None
    source=[]
    for ev in cond.get("evidence",[]):
        for item in ev.get("detail",[]):
            if not item.get("reference","").startswith("DiagnosticReport/"):continue
            report=current(snap,item,"DiagnosticReport")
            check(report["subject"]["reference"]==snap.patient and report["status"] in ("final","amended","corrected")
                  and n.instant(report["issued"])<=snap.at and any((V2_REPORT,"PAT") in codes(c) for c in report.get("category",[])),
                  "Final same-patient pathology report required.")
            conclusions=report.get("conclusionCode",[])
            check(conclusions and all(matches_osteo(c) for c in conclusions),"Pathology coding is unconfirmed or discordant.")
            check({p["reference"] for p in report["performer"]} & set(snap.registry.get("record",[])),
                  "Verify the pathology report issuing organization.")
            specimens=[current(snap,v,"Specimen") for v in report["specimen"]]
            check(specimens and all(s["subject"]["reference"]==snap.patient and s.get("status") in ("available","unavailable") for s in specimens),
                  "Confirm histologic specimen and patient.")
            source.extend([report,*specimens])
    check(source, "No source-linked pathology report with the indexed osteosarcoma diagnosis.")
    return ready("OSTEOSARCOMA",[cond,*source],"Exact osteosarcoma diagnosis and histopathology linked to the indexed specimen.")

def derive(rules,bundle,context):
    snap=n.Snapshot(bundle,context)
    out={}
    errors=(ValueError,TypeError,KeyError,IndexError,AttributeError,OverflowError,InvalidSignature,ZoneInfoNotFoundError)
    r=rules.get("I01") or rules.get("106S01-I01")
    consents=[s for s in snap.current.values() if s["resourceType"]=="Consent" and s.get("patient",{}).get("reference")==snap.patient
              and n.tag(s,VISIT,snap.encounter) and any((FORM,PRESCREEN) in codes(c) for c in s.get("category",[]))]
    if r and consents:
        age_key=n.contract(r["facts"]["age_at_prescreen"]);weight_key=n.contract(r["facts"]["prescreen_weight"])
        try:
            days=[consent_date(snap,context,c) for c in consents]
            check(len({day for day,_ in days})==1, "Conflicting prescreen dates for the same attempt.")
            day=days[0][0];base=[item for _,refs in days for item in refs]
        except errors:
            for key in [age_key,weight_key]:out[key]=missing("Resolve the dated, signed prescreen consent and linked patient/study records.")
        else:
            try:
                age=completed_age(full_date(snap.current[snap.patient]["birthDate"]),day)
                out[age_key]=ready(age,base,"Completed age at the verified prescreen consent date in the site time zone.")
            except errors:
                out[age_key]=missing("Exact birth date and prescreen consent date are required.")
            try:
                val=weight_sources(snap,context,day,base)
                if val:out[weight_key]=val
            except errors:
                out[weight_key]=missing("Resolve weight date, units, conflicts and versioned source on the prescreen consent date.")
    r=rules.get("I17") or rules.get("106S01-I17")
    if r and context.get("index_condition"):
        k=n.contract(r["facts"]["index_histology"])
        try:
            result=pathology(snap,context)
            if result:out[k]=result
        except errors:
            out[k]=missing("Verify the indexed condition, linked histopathology, specimen and institution.")
    return out

def native_example(rules, *, birth="2008-05-01", signing_time="2026-05-01T09:00:00-07:00",
                   weight=30, signer="participant", site_zone="America/Los_Angeles", pathology_case=True):
    """Create a synthetic native-only chart with checkable research signature. No mapped observations are seeded."""
    stamp="2026-05-03T22:00:00Z"
    packet=n.make_packet(rules,{},stamp=stamp);ctx=packet["context"];bundle=packet["bundle"]
    ctx["site_zone"]=site_zone
    by_type={v["resource"]["resourceType"]:v["resource"] for v in bundle["entry"]}
    pt,enc=by_type["Patient"],by_type["Encounter"]
    pt["birthDate"]=birth
    subj={"reference":"Patient/"+pt["id"]};visit={"reference":"Encounter/"+enc["id"]}
    record={"reference":ctx["trusted_roles"]["record"][0]}
    stamp_value=signing_time
    def res(kind,id,**prop):
        return {"resourceType":kind,"id":id,"meta":{"versionId":"1","lastUpdated":stamp},**prop}
    def add(r):
        bundle["entry"].append({"resource":r})
        return r
    signer_ref=subj["reference"] if signer=="participant" else "RelatedPerson/guardian"
    registration={"role":signer,"patient":subj["reference"],"protocol":n.HASH,"from":"2025-01-01T00:00:00Z","through":"2027-01-01T00:00:00Z"}
    if signer!="participant":
        rep=add(res("RelatedPerson","guardian",active=True,patient=subj))
        registration["authority_record"]=n.ref(rep)
    # Deterministic example key, exclusively for synthetic replay.
    sk=Ed25519PrivateKey.from_private_bytes(sha256(b"pocketmd-test-only-prescreen-icf-v1").digest())
    registration["public_key"]=b64(sk.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw))
    ctx["prescreen_signers"]={signer_ref:registration}
    form={"coding":[{"system":FORM,"code":PRESCREEN}]}
    src_tag=[{"system":n.SOURCE,"value":n.HASH}]
    document=add(res("DocumentReference","prescreen",subject=subj,status="current",docStatus="final",type=form,date=stamp_value,
                     context={"encounter":[visit]},identifier=src_tag,author=[record],
                     content=[{"attachment":{"contentType":"text/plain","data":b64(b"Synthetic prescreen consent form.")}}]))
    consent=add(res("Consent","prescreen",patient=subj,status="active",category=[form],scope={"coding":[{"system":"http://terminology.hl7.org/CodeSystem/consentscope","code":"research"}]},
                    dateTime=stamp_value,sourceReference=reference(document),identifier=[
                        {"system":n.STUDY,"value":"106S01|"+n.HASH+"|prescreen"},{"system":VISIT,"value":visit["reference"]}]))
    add(res("Provenance","consent-signature",target=[reference(consent)],recorded=stamp_value,agent=[{"who":{"reference":signer_ref}}],
            signature=[{"type":[{"system":"urn:iso-astm:E1762-95:2013","code":"1.2.840.10065.1.12.1.1"}],"when":stamp_value,"who":{"reference":signer_ref},
                        "sigFormat":SIGN_FORMAT,"data":b64(sk.sign(signing_payload(consent,document,stamp_value,signer_ref)))}]))
    report=add(res("DocumentReference","weight-report",subject=subj,status="current",docStatus="final",date=stamp_value,
                   identifier=src_tag,author=[record],content=[{"attachment":{"contentType":"text/plain","title":"Synthetic weight measurement"}}]))
    add(res("Observation","measured-weight",subject=subj,encounter=visit,status="final",performer=[record],
            effectiveDateTime=stamp_value,issued=stamp_value,code={"coding":[{"system":LOINC,"code":"29463-7"}]},
            valueQuantity={"value":weight,"system":n.UCUM,"code":"kg"},derivedFrom=[reference(report)]))
    if pathology_case:
        coding={"coding":[{"system":ICDO,"code":"9180/3"}]}
        specimen=add(res("Specimen","indexed-biopsy",status="available",subject=subj))
        rpt=add(res("DiagnosticReport","biopsy-report",subject=subj,status="final",code={"text":"Surgical pathology report"},
                    category=[{"coding":[{"system":V2_REPORT,"code":"PAT"}]}],issued=stamp_value,performer=[record],
                    specimen=[reference(specimen)],conclusionCode=[coding]))
        cond=by_type["Condition"]
        cond.update(code=deepcopy(coding),verificationStatus={"coding":[{"system":VERIFY_STATUS,"code":"confirmed"}]},
                    evidence=[{"detail":[reference(rpt)]}])
        ctx['index_condition']=n.ref(cond)
    return packet
