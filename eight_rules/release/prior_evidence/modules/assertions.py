"""Study-scoped research screening of explicit, signed patient and investigator facts.

Input: FHIR R4 Collection Bundle plus a caller-selected patient, exact protocol hash, phase,
screening encounter, as-of time, and separately trusted signer registry. Only synthetic research
keys are provided here; never use the demo key generator for hospital data. Real key enrollment,
revocation, local form mapping, role delegation, and clinical validation are outside this adapter.
Signatures are detached Ed25519 over canonical UTF-8 JSON of one complete QuestionnaireResponse.
Requires cryptography. Run --example, --self-test, or pass an input JSON file.
"""
import argparse
import base64
import hashlib
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def form(study, criterion, phase, digest, combine, items):
    return dict(phase=phase, digest=digest, combine=combine, items=items,
                url=f"https://example.org/pocketmd/research/Questionnaire/{study}/{criterion}|{digest}")


STUDY_CODE = "urn:pocketmd:research:protocol-screening"
RULES = {}
def register(study, criterion, phase, digest, combine, *items):
    RULES[study, criterion] = form(study, criterion, phase, digest, combine, items)

register("REC-1245-101","I11","screening","762f804a6a745b9303138489546d3e7eceb9b4bf7ce8bd1f0d633e3db602b8de","all",
         ("willing","participant","Are you willing to comply with the clinic visits and procedures outlined in this study protocol?"),
         ("able","participant-or-investigator","Is the participant able to comply with the clinic visits and procedures outlined in this study protocol?"))
register("PH-L19TNFDOX2","I10","screening","6697833eab6e9c9ae5ebb8333d8d052a497858e1e9cc11c092a5c95a1b08aa34","all",
         ("willing","participant","Are you willing to comply with the scheduled visits, treatment plan, laboratory tests and other study procedures?"),
         ("able","participant-or-investigator","Is the participant able to comply with the scheduled visits, treatment plan, laboratory tests and other study procedures?"))
register("FOG-001-301","DB-I12","double-blind-entry","f88bd59efffe199a3c8767edcb74d2b98c0e172d1b1f4804087ea0086fc73554","all",
         ("willing","investigator","In your opinion, is this participant willing to comply with all study procedures, assessments and visit schedules?"),
         ("able","investigator","In your opinion, is this participant able to comply with all study procedures, assessments and visit schedules?"))
register("106S01","106S01-E13","screening","6e80a01373fd98d53a3ca3c15d720e3d9bc32e98342db32a54284349b7f6f22a","none",
         ("psychiatric-or-social-barrier","investigator","In your opinion, does a psychiatric condition or social situation preclude this participant's ability to comply with trial requirements?"))
register("1479-0032","E12","screening","70959eefde1c1f6201e9574c8040075b8e0f2b7be1f14bba999ff816d797de6d","all",
         ("expected-compliance","investigator","Do you expect this participant to comply with the protocol requirements?"),
         ("expected-completion","investigator","Do you expect this participant to complete the trial as scheduled?"))

def time(value):
    if not isinstance(value,str) or "T" not in value:
        raise ValueError("An offset-qualified instant is required.")
    value=datetime.fromisoformat(value.replace("Z","+00:00"))
    if value.tzinfo is None:
        raise ValueError("Missing time offset.")
    return value

def canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()

def ref(resource):
    return f"{resource['resourceType']}/{resource['id']}/_history/{resource['meta']['versionId']}"

def rr(value):
    return {"reference":value}

def b64(value):
    return base64.b64encode(value).decode()

def allowed_roles(reporter):
    return ("participant", "investigator") if reporter == "participant-or-investigator" else (reporter,)

def preferred_queue(reporter):
    return "PATIENT_SURVEY" if "participant" in allowed_roles(reporter) else "INVESTIGATOR_ACTIONS"

def evaluate(bundle, context):
    study,criterion=context["study"],context["criterion"]
    rule=RULES[study,criterion]
    evidence=set()
    def result(state,reason,missing=()):
        return {"study":study,"criterion":criterion,"state":state,"reason":reason,
                "evidence":sorted(evidence),"requested_facts":list(missing),"protocol_sha256":rule["digest"]}
    if context.get("protocol_sha256")!=rule["digest"] or context.get("phase")!=rule["phase"]:
        return result("AUTHORING_HOLD","Rule package does not cover this protocol version and phase.")
    if study=="PH-L19TNFDOX2" and context.get("historical_research") is not True:
        return result("AUTHORING_HOLD","Only the supplied historical v6 protocol has been mapped.")
    try:
        as_of=time(context["as_of"])
        pat,enc=context["patient"],context["encounter"]
        if bundle.get("resourceType")!="Bundle" or bundle.get("type")!="collection":
            raise ValueError("Supply the normalized screening snapshot.")
        index={}
        for entry in bundle["entry"]:
            r=entry["resource"]
            if time(r["meta"]["lastUpdated"])>as_of:
                continue
            logical=f"{r['resourceType']}/{r['id']}"
            if logical in index or not r['meta']['versionId'] or r.get("modifierExtension") or r.get("implicitRules"):
                raise ValueError("Invalid or ambiguous snapshot resource.")
            index[logical]=r
        person,visit=index[pat],index[enc]
        if person["resourceType"]!="Patient" or visit["resourceType"]!="Encounter" or visit["subject"]!=rr(pat):
            raise ValueError("Verify the screening patient and encounter.")
        binding="|".join([study,rule["digest"],rule["phase"]])
        if [i["value"] for i in visit.get("identifier",[]) if i.get("system")==STUDY_CODE]!=[binding]:
            raise ValueError("Verify study, protocol and phase at this encounter.")
        if visit.get("status") not in {"in-progress","finished"}:
            raise ValueError("Screening encounter is not active or completed.")
        start=time(visit["period"]["start"])
        end=min(as_of,time(visit["period"]["end"])) if visit["period"].get("end") else as_of
        if end<start:
            raise ValueError("Encounter outside snapshot.")
        evidence.update([ref(person),ref(visit)])
        schema={item:(role,label) for item,role,label in rule["items"]}
        values={item:set() for item in schema}
        for response in index.values():
            if (response['resourceType']!="QuestionnaireResponse" or response.get("questionnaire")!=rule["url"]
                or response.get("subject")!=rr(pat) or response.get("encounter")!=rr(enc)
                or response.get("status") not in {"completed","amended"}):
                continue
            authored=time(response["authored"])
            if not start<=authored<=end:
                continue
            actor=response.get("source",{}).get("reference")
            if not actor or actor not in index:
                raise ValueError("Respondent identity is unavailable.")
            actor_record=index[actor]
            role="participant" if actor==pat else "investigator"
            trusted=context.get("trusted_signers",{}).get(actor)
            if not trusted or trusted["study"]!=study or trusted["role"]!=role or trusted["protocol_sha256"]!=rule["digest"]:
                raise ValueError("Unverified respondent or protocol assignment.")
            if not time(trusted["start"])<=authored<=time(trusted["end"]):
                raise ValueError("Respondent authority outside its verified validity interval.")
            if role=="investigator" and (actor_record.get("resourceType")!="PractitionerRole" or actor_record.get("active") is not True
                    or not any(i.get("system")==STUDY_CODE and i.get("value")==binding for i in actor_record.get("identifier",[]))):
                raise ValueError("Investigator is not assigned to this study phase.")
            refs=[p for p in index.values() if p["resourceType"]=="Provenance" and p.get("target")==[rr(ref(response))]]
            proofs=[]
            for p in refs:
                for sig in p.get("signature",[]):
                    if sig.get("who")!=rr(actor) or sig.get("sigFormat")!="application/ed25519-signature" or not authored<=time(sig["when"])<=time(p["recorded"])<=as_of:
                        continue
                    if not any(a.get('who')==rr(actor) for a in p.get('agent',[])):
                        continue
                    key=Ed25519PublicKey.from_public_bytes(base64.b64decode(trusted['ed25519_public'],validate=True))
                    key.verify(base64.b64decode(sig["data"],validate=True),canonical(response))
                    proofs.append(ref(p))
            if not proofs:
                raise ValueError("Missing a verified signature on the precise response version.")
            evidence.update([ref(response),ref(actor_record),*proofs])
            seen=set()
            for item in response["item"]:
                code=item["linkId"]
                if code in seen or code not in schema or role not in allowed_roles(schema[code][0]) or schema[code][1]!=item.get("text") or item.get("item"):
                    raise ValueError("Unrecognized, duplicated or wrongly attributed question.")
                seen.add(code)
                answers=item.get("answer",[])
                if len(answers)!=1 or set(answers[0])!={"valueBoolean"} or type(answers[0]["valueBoolean"]) is not bool:
                    raise ValueError("An explicit response to this named fact is required.")
                values[code].add(answers[0]["valueBoolean"])
        conflicted=[item for item,val in values.items() if len(val)>1]
        if conflicted:
            return result("MISSING_DATA","Reconcile conflicting signed answers for the same screening.",conflicted)
        for val in values.values():
            if (rule["combine"]=="none" and True in val) or (rule["combine"]=="all" and False in val):
                return result("NOT_MET","A signed answer establishes a disqualifying finding.")
        missing=[item for item,val in values.items() if not val]
        if missing:
            owner="PATIENT_SURVEY" if any("participant" in allowed_roles(schema[i][0]) for i in missing) else "INVESTIGATOR_ACTIONS"
            return result(owner,"Obtain the outstanding patient-specific response(s).",missing)
        return result("MET","All named facts are established by signed scoped evidence.")
    except (AttributeError,ValueError,KeyError,IndexError,TypeError,InvalidSignature):
        return result("MISSING_DATA","Verify the exact source record, signature, identity, study and timing before screening.")

def demo_key(actor):
    # EXAMPLES ONLY. Real callers enroll trusted public keys out of band.
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(("PUBLIC-SYNTHETIC-KEY:"+actor).encode()).digest())

def example(study="REC-1245-101",criterion="I11",vals=None,reporters=None):
    rule=RULES[study,criterion]
    reporters=reporters or {}
    pat,enc,investigator="Patient/demo","Encounter/screen","PractitionerRole/site"
    date="2026-11-19T10:00:00Z"
    binding="|".join((study,rule["digest"],rule["phase"]))
    identifier=[{"system":STUDY_CODE,"value":binding}]
    rows=[]
    def add(rt,id,**fields):
        r=dict(resourceType=rt,id=id,meta={"versionId":"1","lastUpdated":date},**fields);rows.append({"resource":r});return r
    add("Patient","demo")
    add("Encounter","screen",subject=rr(pat),status="in-progress",identifier=identifier,
        period={"start":"2026-11-19T08:00:00Z"},**{"class":{"system":"http://terminology.hl7.org/CodeSystem/v3-ActCode","code":"AMB"}})
    add("Practitioner","site-md")
    add("PractitionerRole","site",active=True,practitioner=rr("Practitioner/site-md"),identifier=identifier)
    context=dict(study=study,criterion=criterion,protocol_sha256=rule["digest"],phase=rule["phase"],as_of=date,patient=pat,encounter=enc,
                 trusted_signers={},historical_research=study=="PH-L19TNFDOX2")
    responses={item:rule["combine"]=="all" for item,_,_ in rule["items"]} if vals is None else vals
    for role in ["participant","investigator"]:
        actor=pat if role=="participant" else investigator
        key=demo_key(actor);public=key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
        context["trusted_signers"][actor]={"study":study,"role":role,"protocol_sha256":rule["digest"],
            "start":"2026-01-01T00:00:00Z","end":"2026-12-31T23:59:59Z","ed25519_public":b64(public)}
        group=[{"linkId":i,"text":question,"answer":[{"valueBoolean":responses[i]}]} for i,reporter,question in rule["items"]
               if reporters.get(i,allowed_roles(reporter)[0])==role and i in responses]
        if not group:continue
        obj=add("QuestionnaireResponse",role,questionnaire=rule["url"],subject=rr(pat),source=rr(actor),author=rr(actor),encounter=rr(enc),
                authored=date,status="completed",item=group)
        add("Provenance","sign-"+role,target=[rr(ref(obj))],recorded=date,agent=[{"who":rr(actor)}],signature=[{
            "type":[{"system":"urn:iso-astm:E1762-95:2013","code":"1.2.840.10065.1.12.1.1"}],"when":date,"who":rr(actor),
            "sigFormat":"application/ed25519-signature","data":b64(key.sign(canonical(obj)))}])
    return {"context":context,"bundle":{"resourceType":"Bundle","type":"collection","entry":rows}}

def run_checks():
    rows=[]
    for (study,criterion),rule in RULES.items():
        def test(case,expected,packet):
            actual=evaluate(packet["bundle"],packet["context"])["state"]
            rows.append(dict(study=study,criterion=criterion,case=case,expected=expected,actual=actual))
        base=example(study,criterion);ok=rule["combine"]=="all"
        test("complete signed facts","MET",base)
        items=rule["items"]
        for key,role,_ in items:
            vals={i:ok for i,_,_ in items}
            vals[key]=not ok
            test("decisive contrary answer: "+key,"NOT_MET",example(study,criterion,vals))
            del vals[key]
            test("missing "+key,preferred_queue(role),example(study,criterion,vals))
        if any(reporter=="participant-or-investigator" for _,reporter,_ in items):
            test("participant reports own ability","MET",base)
            investigator=example(study,criterion,reporters={"able":"investigator"})
            test("investigator documents ability","MET",investigator)
            conflicting=deepcopy(base)
            contrary=example(study,criterion,{"able":False},{"able":"investigator"})
            conflicting["bundle"]["entry"].extend(
                e for e in contrary["bundle"]["entry"] if e["resource"]["resourceType"] in {"QuestionnaireResponse","Provenance"})
            test("conflicting signed participant and investigator ability responses","MISSING_DATA",conflicting)
            test("investigator cannot substitute their own statement for participant willingness","MISSING_DATA",
                 example(study,criterion,reporters={"willing":"investigator"}))
        elif study=="FOG-001-301":
            test("participant alone cannot supply the investigator's specified opinion","MISSING_DATA",
                 example(study,criterion,reporters={"willing":"participant","able":"participant"}))
        bad=deepcopy(base)
        response=next(e["resource"] for e in bad["bundle"]["entry"] if e["resource"]["resourceType"]=="QuestionnaireResponse")
        response["item"]=[{"linkId":"eligible","text":"Is this patient eligible?","answer":[{"valueBoolean":True}]}]
        proof=next(e["resource"] for e in bad["bundle"]["entry"] if e["resource"]["resourceType"]=="Provenance" and e["resource"]["target"]==[rr(ref(response))])
        proof["signature"][0]["data"]=b64(demo_key(response["source"]["reference"]).sign(canonical(response)))
        test("authenticated generic eligibility checkbox","MISSING_DATA",bad)
        bad=deepcopy(base);bad["context"]["protocol_sha256"]="other";test("wrong amendment","AUTHORING_HOLD",bad)
        bad=deepcopy(base);bad["context"]["phase"]="other";test("wrong cohort phase","AUTHORING_HOLD",bad)
        bad=deepcopy(base)
        response=next(r["resource"] for r in bad["bundle"]["entry"] if r["resource"]["resourceType"]=="QuestionnaireResponse")
        response["item"][0]["answer"][0]["valueBoolean"]=not ok;test("altered after signing","MISSING_DATA",bad)
        bad=deepcopy(base)
        bad["bundle"]["entry"]=[r for r in bad["bundle"]["entry"] if r["resource"]["resourceType"]!="Provenance"]
        test("unsigned responses","MISSING_DATA",bad)
        bad=deepcopy(base); bad["context"]["trusted_signers"]={};test("untrusted reporter","MISSING_DATA",bad)
        bad=deepcopy(base)
        answers=[r["resource"] for r in bad["bundle"]["entry"] if r["resource"]["resourceType"]=="QuestionnaireResponse"]
        for ans in answers:ans["subject"]=rr("Patient/other")
        missing_first="PATIENT_SURVEY" if any(role=="participant" for _,role,_ in items) else "INVESTIGATOR_ACTIONS"
        test("other patient answers ignored",missing_first,bad)
        bad=deepcopy(base)
        for e in bad["bundle"]["entry"]:
            if e["resource"]["resourceType"]=="QuestionnaireResponse":e["resource"]["encounter"]=rr("Encounter/later")
        test("other encounter ignored",missing_first,bad)
        if study=="PH-L19TNFDOX2":
            bad=deepcopy(base);bad["context"]["historical_research"]=False;test("historical version not authorized for current screening","AUTHORING_HOLD",bad)
    return rows

if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("input",nargs="?",type=Path)
    cli.add_argument("--example",nargs=2,metavar=("STUDY","CRITERION"))
    cli.add_argument("--self-test",action="store_true")
    args=cli.parse_args()
    if args.self_test:
        rows=run_checks();print(json.dumps(rows,indent=2));raise SystemExit(any(r["actual"]!=r["expected"] for r in rows))
    if args.example:
        print(json.dumps(example(*args.example),indent=2));raise SystemExit
    if not args.input:cli.error("Supply an input JSON, --example STUDY CRITERION, or --self-test.")
    data=json.loads(args.input.read_text());print(json.dumps(evaluate(data["bundle"],data["context"]),indent=2))
