"""Reduce typed evidence under a pinned research normalization profile.

The input producer must establish each catalogued clinical scope before emitting a
fact. A code match on an unrestricted hospital observation is insufficient.
"""
from datetime import datetime
from hashlib import sha256
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
HASH = "6e80a01373fd98d53a3ca3c15d720e3d9bc32e98342db32a54284349b7f6f22a"
PROFILE = "urn:pocketmd:research:screening-fact:v1"
FACTS = "urn:pocketmd:research:normalized-evidence:v1"
SOURCE = "urn:pocketmd:research:screening-source:v1"
STUDY = "urn:pocketmd:research:protocol-screening"
UCUM = "http://unitsofmeasure.org"
DATA_STATES = {"MISSING_DATA", "INVESTIGATOR_ACTIONS", "PATIENT_SURVEY", "STUDY_ACTION"}
PRIORITY = ["BINDING_HOLD","AUTHORING_HOLD","MISSING_DATA","STUDY_ACTION","INVESTIGATOR_ACTIONS","PATIENT_SURVEY"]
ROLE_MISSING = {"record":"MISSING_DATA","site":"STUDY_ACTION","investigator":"INVESTIGATOR_ACTIONS","patient":"PATIENT_SURVEY"}
SAFE = re.compile(r"^[A-Za-z0-9.-]{1,64}$")

def instant(value):
    if not isinstance(value,str) or "T" not in value: raise ValueError("An offset-qualified instant is required.")
    t=datetime.fromisoformat(value.replace("Z","+00:00"))
    if t.utcoffset() is None: raise ValueError("An offset-qualified instant is required.")
    return t

def canonical(data):
    return json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()

def contract(fact):
    return "f-"+sha256(canonical(fact)).hexdigest()[:24]

def ref(r):
    return f"{r['resourceType']}/{r['id']}/_history/{r['meta']['versionId']}"

def relative(v,kind):
    if not isinstance(v,str): raise ValueError(f"Supply a valid {kind} identifier.")
    rid=v.removeprefix(kind+"/")
    if not SAFE.fullmatch(rid) or rid in {".",".."}: raise ValueError(f"Invalid {kind} identifier.")
    return kind+"/"+rid

def tag(r,system,value):
    return any(x.get("system")==system and x.get("value")==value for x in r.get("identifier",[]) if isinstance(x,dict))

class Snapshot:
    def __init__(self, bundle, context):
        if bundle.get("resourceType")!="Bundle" or bundle.get("type")!="collection": raise ValueError("Supply a normalized FHIR collection Bundle.")
        if context.get("study")!="106S01" or context.get("protocol_sha256")!=HASH: raise ValueError("Study or protocol fingerprint mismatch.")
        self.at=instant(context["as_of"])
        self.patient=relative(context["patient"],"Patient")
        self.encounter=relative(context["encounter"],"Encounter")
        self.episode=relative(context["episode"],"Condition") if context.get("episode") else None
        self.native={}
        self.exact={}
        self.current={}
        self.enabled=set(context.get("enabled_contracts",[]))
        self.registry=context.get("trusted_roles",{})
        if not isinstance(self.registry,dict): raise ValueError("Invalid signer-role configuration.")
        latest={}
        for entry in bundle.get("entry",[]):
            r=entry.get("resource") or {}
            meta=r.get("meta") or {}
            if not isinstance(r.get("id"),str) or not SAFE.fullmatch(r["id"]) or not meta.get("versionId") or not meta.get("lastUpdated"):
                continue
            stamp=instant(meta["lastUpdated"])
            if stamp>self.at: continue
            version=ref(r)
            if version in self.exact and self.exact[version]!=r: raise ValueError("Conflicting copies of a resource version.")
            self.exact[version]=r
            key=version.split("/_history/")[0]
            if key not in latest or stamp>latest[key]:
                latest[key]=stamp;self.current[key]=r
            elif stamp==latest[key] and self.current[key]!=r: raise ValueError("Ambiguous as-of resource version.")
        enc=self.current.get(self.encounter,{})
        if self.patient not in self.current or enc.get("subject",{}).get("reference")!=self.patient or not tag(enc,STUDY,"106S01|"+HASH+"|screening"):
            raise ValueError("Patient and study encounter are not linked to this protocol snapshot.")
        if self.episode and self.current.get(self.episode,{}).get("subject",{}).get("reference")!=self.patient:
            raise ValueError("The index condition does not belong to the selected patient.")
        self.by_code={}
        for obs in self.current.values():
            if obs.get("resourceType")!="Observation" or obs.get("subject",{}).get("reference")!=self.patient or obs.get("encounter",{}).get("reference")!=self.encounter:
                continue
            for c in obs.get("code",{}).get("coding",[]):
                if c.get("system")==FACTS and c.get("version")==HASH:
                    self.by_code.setdefault(c.get("code"),[]).append(obs)

    def read(self,fact):
        key=contract(fact)
        if key not in self.enabled:
            return None,"BINDING_HOLD",[],f"Enable a validated normalized mapping for {fact['label']}."
        found=[]
        native=self.native.get(key)
        if native is not None:
            if native[1]: return native
            found.append((native[0],native[2]))
        for obs in self.by_code.get(key,[]):
            if obs.get("status") in ("entered-in-error","cancelled"): continue
            if not self.episode or [r.get("reference") for r in obs.get("focus",[])]!=[self.episode]: continue
            try:
                if (PROFILE not in obs["meta"].get("profile",[]) or obs["status"] not in ("final","amended","corrected") or
                    obs.get("modifierExtension") or obs.get("implicitRules") or instant(obs["effectiveDateTime"])>self.at or
                    instant(obs["issued"])>self.at or instant(obs["effectiveDateTime"])>instant(obs["issued"])):
                    raise ValueError()
                docs=obs["derivedFrom"]
                if not isinstance(docs,list) or not docs: raise ValueError()
                refs=[ref(obs)]
                for reference in docs:
                    src=self.exact[reference["reference"]]
                    if (src.get("resourceType")!="DocumentReference" or src.get("status")!="current" or src.get("modifierExtension") or
                        self.current.get("DocumentReference/"+src["id"])!=src or
                        src.get("subject",{}).get("reference")!=self.patient or
                        not tag(src,SOURCE,HASH) or instant(src["date"])>self.at):
                        raise ValueError()
                    authors={a["reference"] for a in src["author"]}
                    performers={a["reference"] for a in obs["performer"]}
                    if fact["role"]=="patient": permitted={self.patient}
                    else: permitted=set(self.registry.get(fact["role"],[]))
                    if not authors & performers & permitted: raise ValueError()
                    refs.append(ref(src))
                choices=[k for k in obs if k.startswith("value")]
                if len(choices)!=1: raise ValueError()
                kind=fact["kind"]
                if kind=="bool" and choices==["valueBoolean"] and type(obs["valueBoolean"])==bool:
                    value=obs["valueBoolean"]
                elif kind=="number" and choices==["valueQuantity"]:
                    q=obs["valueQuantity"]
                    if q.get("comparator") or (q.get("system"),q.get("code"))!=(UCUM,fact["unit"]): raise ValueError()
                    value=q["value"]
                    if type(value) not in (float,int) or not math.isfinite(value): raise ValueError()
                    if value<fact.get("minimum",-math.inf) or value>fact.get("maximum",math.inf) or value<=fact.get("exclusiveMinimum",-math.inf): raise ValueError()
                    if fact.get("integer") and value!=int(value): raise ValueError()
                elif kind=="code" and choices==["valueCodeableConcept"]:
                    codings=obs["valueCodeableConcept"]["coding"]
                    vals={c["code"] for c in codings if c.get("system")==FACTS+"/"+key}
                    if len(vals)!=1: raise ValueError()
                    value=vals.pop()
                    if value not in fact["values"]: raise ValueError()
                else: raise ValueError()
                found.append((value,refs))
            except (ValueError,KeyError,TypeError,OverflowError):
                return None,"MISSING_DATA",[],f"Verify the typed, scoped evidence and source for {fact['label']}."
        if not found:
            return None,ROLE_MISSING[fact["role"]],[],f"Obtain {fact['label']}."
        refs=sorted({s for _,items in found for s in items})
        if len({v for v,_ in found})!=1: return None,"MISSING_DATA",refs,f"Reconcile conflicting records for {fact['label']}."
        return found[0][0],None,refs,fact["label"]

def result(state,reason,evidence=()):
    return {"state":state,"reason":reason,"evidence":sorted(set(evidence))}

def fold(items, conjunction):
    wanted="NOT_MET" if conjunction else "MET"
    opposite="MET" if conjunction else "NOT_MET"
    cases=[r for r in items if r["state"]==wanted]
    if cases: state=wanted
    elif all(r["state"]==opposite for r in items): state=opposite;cases=items
    else:
        state=next(s for s in PRIORITY if any(r["state"]==s for r in items))
        cases=[r for r in items if r["state"]==state]
    return result(state," ".join(dict.fromkeys(x['reason'] for x in cases)),[e for x in cases for e in x["evidence"]])

def evaluate(rule,snapshot):
    trace={}
    def visit(node):
        if "fact" in node:
            k=node["fact"];spec=rule["facts"][k]
            if k not in trace: trace[k]=snapshot.read(spec)
            value,issue,refs,why=trace[k]
            if issue: return result(issue,why,refs)
            want=node["value"];op=node["op"]
            operations={"eq":lambda:value==want,"in":lambda:value in want,"lt":lambda:value<want,
                        "gt":lambda:value>want,"le":lambda:value<=want,"ge":lambda:value>=want}
            passed=operations[op]()
            return result("MET" if passed else "NOT_MET",f"{spec['label']} = {value} (requires {op} {want}).",refs)
        if "const" in node: return result("MET" if node["const"] else "NOT_MET","Protocol branch applies.")
        if "hold" in node: return result("AUTHORING_HOLD",node["hold"])
        if "missing" in node: return result("MISSING_DATA",node["missing"])
        if "not" in node:
            r=visit(node["not"]);return {**r,"state":{"MET":"NOT_MET","NOT_MET":"MET"}.get(r["state"],r["state"])}
        if "if" in node:
            cond,yes,no=node["if"];r=visit(cond)
            if r["state"] in ("MET","NOT_MET"):
                selected=visit(yes if r['state']=="MET" else no)
                return result(selected["state"],selected["reason"],r["evidence"]+selected["evidence"])
            a,b=visit(yes),visit(no)
            if a["state"]==b["state"] and a["state"] in ("MET","NOT_MET"):
                return result(a["state"],"Both applicable interpretations agree. "+a["reason"]+" "+b["reason"],a["evidence"]+b["evidence"])
            return r
        if "all" in node: return fold([visit(v) for v in node["all"]],True)
        if "any" in node: return fold([visit(v) for v in node["any"]],False)
        raise ValueError("Unknown operator in released rule.")
    out=visit(rule["expression"])
    out["facts"]={k:{"label":rule["facts"][k]["label"],"value":v,"state":s or "AVAILABLE","evidence":e} for k,(v,s,e,_) in trace.items()}
    return out

def make_packet(rules,values_by_rule,patient="demo",encounter="screen",stamp="2026-05-01T12:00:00Z"):
    ctx={"study":"106S01","protocol_sha256":HASH,"patient":patient,"encounter":encounter,"episode":"index-"+patient,"as_of":stamp,"site_zone":"UTC",
         "enabled_contracts":sorted({contract(f) for r in rules.values() for f in r['facts'].values()}),
         "trusted_roles":{"record":["Organization/demo-record"],"investigator":["PractitionerRole/demo-investigator"],"site":["Organization/demo-site"]}}
    def resource(kind,ident,**props):
        return {"resourceType":kind,"id":ident,"meta":{"versionId":"1","lastUpdated":stamp},**props}
    subject={"reference":"Patient/"+patient}
    encref={"reference":"Encounter/"+encounter}
    entries=[resource("Patient",patient),resource("Condition","index-"+patient,subject=subject),resource("Encounter",encounter,status="in-progress",**{"class":{"system":"http://terminology.hl7.org/CodeSystem/v3-ActCode","code":"AMB"}},subject=subject,
             period={"start":stamp},identifier=[{"system":STUDY,"value":"106S01|"+HASH+"|screening"},{"system":"urn:pocketmd:demo:screening-study","value":"106S01"}])]
    seen={}
    for cid,values in values_by_rule.items():
        for key,value in values.items():
            f=rules[cid]["facts"][key];code=contract(f)
            if code in seen:
                if seen[code]!=value: raise ValueError("Synthetic scenarios disagree about a shared fact.")
                continue
            seen[code]=value
            who=subject if f["role"]=="patient" else {"reference":ctx["trusted_roles"][f["role"]][0]}
            doc=resource("DocumentReference","src-"+code,status="current",subject=subject,date=stamp,author=[who],
                         identifier=[{"system":SOURCE,"value":HASH}],content=[{"attachment":{"contentType":"text/plain","title":"Synthetic source for "+f["label"]}}])
            obs=resource("Observation","obs-"+code,status="final",subject=subject,encounter=encref,
                         effectiveDateTime=stamp,issued=stamp,focus=[{"reference":"Condition/index-"+patient}],performer=[who],derivedFrom=[{"reference":ref(doc)}],
                         code={"coding":[{"system":FACTS,"version":HASH,"code":code,"display":f["label"]}]})
            obs['meta']['profile']=[PROFILE]
            if f["kind"]=="bool": obs["valueBoolean"]=value
            elif f["kind"]=="number": obs["valueQuantity"]={"value":value,"system":UCUM,"code":f["unit"]}
            else: obs["valueCodeableConcept"]={"coding":[{"system":FACTS+"/"+code,"code":value}]}
            entries.extend([doc,obs])
    return {"context":ctx,"bundle":{"resourceType":"Bundle","type":"collection","entry":[{"resource":r} for r in entries]}}
