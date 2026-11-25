"""Derive SOTIO E05 facts from a bounded, medication-reconciled research R4 snapshot.

Caller trust is out-of-band: therapy_receipts binds a resource's exact bytes to a
trusted current source document for the same patient and protocol. Input bundles
cannot self-certify history coverage. List entries represent reconciled, delivered
products through an actual first-dose anchor. Planned starts are tagged separately
and do not establish future complete exposure. Unknown local products, ingredients
of unresolved combinations and unvalidated half-lives withhold the affected fact.
No real site's drug crosswalk or pharmacokinetic reference is supplied here.
"""
from base64 import b64decode
from decimal import Decimal
from functools import lru_cache
from hashlib import sha256
import json
import math
from pathlib import Path

import normalized as n

ROOT = Path(__file__).resolve().parent
RX = "http://www.nlm.nih.gov/research/umls/rxnorm"
SESSION = "urn:pocketmd:research:sotio-medication-events"
SUPPORT = "urn:pocketmd:research:sotio-medication-evidence"
THROUGH = SUPPORT + "/history-through"
DRUG = "any_listed_inhibitor"
DAYS = "min_inhibitor_stop_days"
LIVES = "min_inhibitor_elapsed_halflives"


@lru_cache(maxsize=1)
def appendix():
    path = ROOT / "sotio_inhibitors.json"
    if not path.is_file(): path = ROOT.parent / "sotio_inhibitors.json"
    data = json.loads(path.read_text())
    if data["source_protocol_sha256"] != n.HASH or data["system"] != RX:
        raise ValueError("Unexpected SOTIO appendix terminology.")
    groups = {frozenset(ids) for rows in data["lists"].values() for row in rows
              for ids in row["any_of_all_ingredient_codes"]}
    return groups, {r["code"] for r in data["ingredients"]}


def codes(value, system):
    return {c["code"] for c in (value or {}).get("coding", []) if c.get("system")==system and c.get("code")}


def code_pair(value):
    pairs={(item.get("system"),item.get("code")) for item in (value or {}).get("coding", [])}
    if len(pairs)!=1 or not all(next(iter(pairs))): raise ValueError("Provide an exact route identity.")
    return next(iter(pairs))


def refid(resource):
    return n.ref(resource).split("/_history/")[0]


def validated(snap, ctx, resource):
    if snap.current.get(refid(resource)) != resource: raise ValueError("Stale resource version.")
    if resource.get("implicitRules") or resource.get("modifierExtension"): raise ValueError("Unexpected FHIR modifiers.")
    pointer=n.ref(resource)
    receipt=ctx.get("therapy_receipts",{}).get(pointer,{})
    doc=snap.exact.get(receipt.get("source"),{})
    if (not doc or doc.get("resourceType")!="DocumentReference" or doc.get("status")!="current" or
        doc.get("modifierExtension") or doc.get("implicitRules") or snap.current.get(refid(doc))!=doc or
        doc.get("subject",{}).get("reference")!=snap.patient or not n.tag(doc,n.SOURCE,n.HASH) or
        n.instant(doc["date"])>snap.at or not doc.get("content")):
        raise ValueError("A current source document for this patient and protocol is needed.")
    # A title-only DocumentReference cannot carry the source asserted by this profile.
    if not any(att.get("contentType") and att.get("data") and b64decode(att["data"],validate=True)
               for entry in doc["content"] for att in [entry.get("attachment",{})]):
        raise ValueError("The source receipt must cover the attached source content.")
    allowed=set(snap.registry.get("record",[]))|set(snap.registry.get("site",[]))
    authors={a.get("reference") for a in doc.get("author",[])}
    if not (authors&allowed) or receipt.get("sha256")!=sha256(n.canonical([resource,doc])).hexdigest():
        raise ValueError("The resource is not bound to a trusted source receipt.")
    return {pointer,n.ref(doc)}


def scoped(snap, r):
    return r.get("subject",{}).get("reference")==snap.patient


def actual_anchor(r):
    if r.get("status") not in ("completed","in-progress"): raise ValueError("No actual first administration.")
    if codes(r.get("medicationCodeableConcept"), SUPPORT)!={"SOT106"} or "medicationReference" in r:
        raise ValueError("First dose did not identify the SOT106 study medication.")
    dt=r.get("effectiveDateTime")
    if dt and "effectivePeriod" in r: raise ValueError("Multiple administration timestamps.")
    return n.instant(dt or r["effectivePeriod"]["start"])


def first_dose(snap, ctx):
    """An active future medication order can support positive historical exposure only."""
    actual=[r for r in snap.current.values() if scoped(snap,r) and r.get("resourceType")=="MedicationAdministration"
            and n.tag(r,SESSION,n.HASH+"|first-SOT106") and r.get("status") not in ("entered-in-error","not-done")]
    if actual:
        if len(actual)!=1: raise ValueError("Conflicting actual first-dose records.")
        r=actual[0]
        moment=actual_anchor(r)
        if moment>snap.at or r.get("context",{}).get("reference")!=snap.encounter: raise ValueError("Invalid first-dose scope.")
        return r,moment,True,validated(snap,ctx,r)
    plans=[r for r in snap.current.values() if scoped(snap,r) and r.get("resourceType")=="MedicationRequest"
           and n.tag(r,SESSION,n.HASH+"|planned-first-SOT106") and r.get("status")=="active"]
    if len(plans)!=1: raise ValueError("A unique documented first-dose order is required.")
    r=plans[0]
    if (r.get("intent")!="order" or r.get("doNotPerform") or
        r.get("encounter",{}).get("reference")!=snap.encounter or
        codes(r.get("medicationCodeableConcept"),SUPPORT)!={"SOT106"} or "medicationReference" in r or
        n.instant(r["authoredOn"])>snap.at or len(r["dosageInstruction"])!=1):
        raise ValueError("Eligibility requires a scoped affirmative medication order.")
    events=r["dosageInstruction"][0]["timing"]["event"]
    if len(events)!=1: raise ValueError("A single explicit scheduled first dose is required.")
    moment=n.instant(events[0])
    if moment<=snap.at: raise ValueError("The planned time has passed without verified administration.")
    return r,moment,False,validated(snap,ctx,r)


def exposure(snap,ctx,r):
    if r.get("status") not in ("completed","stopped","in-progress"): raise ValueError("Unsupported exposure status.")
    refs=validated(snap,ctx,r)
    if "medicationCodeableConcept" in r or "medicationReference" not in r:
        raise ValueError("Supply the exact medication product and its full ingredient list.")
    medication=snap.exact[r["medicationReference"]["reference"]]
    if medication["resourceType"]!="Medication" or medication.get("status")!="active":
        raise ValueError("A verified normalized medication product is needed.")
    refs |= validated(snap,ctx,medication)
    if not medication.get("ingredient"): raise ValueError("Ingredient decomposition missing.")
    ingredient_ids=set()
    for ing in medication["ingredient"]:
        if ing.get("isActive") is False: continue
        if ing.get("isActive") is not True: raise ValueError("Ingredient activity was not verified.")
        choices=codes(ing.get("itemCodeableConcept"),RX)
        if len(choices)!=1: raise ValueError("Missing or ambiguous active ingredient.")
        ingredient_ids.update(choices)
    if not ingredient_ids: raise ValueError("No active ingredient identity.")
    date=r.get("effectiveDateTime")
    period=r.get("effectivePeriod")
    if bool(date)==bool(period): raise ValueError("Missing or ambiguous exposure time.")
    if date:
        if r["status"]!="completed": raise ValueError("Instant must be a documented completed dose.")
        start=end=n.instant(date)
    else:
        start=n.instant(period['start'])
        end=n.instant(period['end']) if period.get('end') else None
        if end and (end<start or end>snap.at): raise ValueError("Invalid or future stop date.")
        if not end and r["status"]!="in-progress": raise ValueError("Document the cessation time.")
    if start>snap.at: raise ValueError("Future exposure.")
    return ingredient_ids,start,end,refs


def as_days(delta):
    return Decimal(delta.days)+Decimal(delta.seconds)/86400+Decimal(delta.microseconds)/86400000000


def half_lives(snap,ctx,administration,ids):
    """Each PK observation cites that exact exposure, same route and a specific inhibitor ingredient."""
    target=n.ref(administration)
    route=code_pair(administration.get("dosage",{}).get("route"))
    found={}
    allrefs=set()
    for r in snap.current.values():
        if r.get("resourceType")!="Observation" or not scoped(snap,r) or codes(r.get("code"),SUPPORT)!={"elimination-half-life"}:
            continue
        if [f.get("reference") for f in r.get("focus",[])] != [target]: continue
        if r.get("status") in ("cancelled","entered-in-error"): continue
        if (r.get("status") not in ("final","amended","corrected") or
            r.get("encounter",{}).get("reference")!=snap.encounter or
            not n.instant(r["effectiveDateTime"])<=n.instant(r["issued"])<=snap.at):
            raise ValueError("Unusable PK source.")
        refs=validated(snap,ctx,r)
        component={}
        for c in r.get("component",[]):
            key=codes(c.get("code"), SUPPORT)
            if len(key)!=1 or next(iter(key)) in component: raise ValueError("Ambiguous PK qualifiers.")
            component[next(iter(key))]=c["valueCodeableConcept"]
        if code_pair(component["route"])!=route: raise ValueError("Route mismatch.")
        ingredient=codes(component["ingredient"],RX)
        if len(ingredient)!=1: raise ValueError("Unverified ingredient for half-life.")
        ingredient=ingredient.pop()
        if ingredient not in ids: continue
        qty=r["valueQuantity"]
        if qty.get("comparator") or qty.get("system")!=n.UCUM or qty.get("code") not in ("h","d"):
            raise ValueError("Half-life requires exact elapsed hours or days.")
        if type(qty.get("value")) not in (float,int): raise ValueError("Half-life is not numeric.")
        v=Decimal(str(qty['value']))/(24 if qty['code']=='h' else 1)
        if not v.is_finite() or v<=0 or (ingredient in found and found[ingredient]!=v): raise ValueError("Invalid or conflicting half-life.")
        found[ingredient]=v
        allrefs |= refs
    if set(found)!=ids: raise ValueError("Product-, ingredient- and route-qualified half-life unavailable.")
    return max(found.values()),allrefs


def has_coverage(snap,ctx,actual,history,anchor_ref):
    lists=[r for r in snap.current.values() if r.get("resourceType")=="List" and scoped(snap,r)
           and r.get('encounter',{}).get('reference')==snap.encounter and codes(r.get('code'),SUPPORT)=={'complete-administered-drug-history'}]
    if len(lists)!=1: return set()
    r=lists[0]
    refs=validated(snap,ctx,r)
    # This is an attested full history to the anchor, not a date range inferred from available events.
    through=[e.get("valueInstant") for e in r.get("extension",[]) if e.get("url")==THROUGH]
    when=n.instant(r["date"])
    if (r.get("status")!="current" or r.get("mode")!="snapshot" or len(through)!=1 or
        not actual<=n.instant(through[0])<=when<=snap.at): return set()
    members=[]
    for ent in r.get("entry",[]):
        if ent.get("deleted") or ent.get("flag") or ent.get("modifierExtension"): return set()
        members.append(ent["item"]["reference"])
    if not members and not codes(r.get("emptyReason"),"http://terminology.hl7.org/CodeSystem/list-empty-reason")=={"nilknown"}: return set()
    if len(members)!=len(set(members)) or anchor_ref in members or set(members)!=history: return set()
    return refs


def derive(rules,bundle,context):
    """Return contract-keyed tuples. An absent key lets the caller use its own trusted normalized record."""
    rule=rules.get("E05") or rules.get("106S01-E05")
    if not rule or not context.get("therapy_receipts"): return {}
    snap=n.Snapshot(bundle,context)
    groups,known=appendix()
    try:
        anchor,start,is_actual,anchor_refs=first_dose(snap,context)
    except (KeyError,TypeError,ValueError,ArithmeticError):return {}
    refs=set(anchor_refs)
    present=set()
    positives=[]
    complete=True
    history=set()
    # Snapshot intentionally ignores resources lacking usable history identifiers.
    # An unversioned delivered-drug row must nevertheless invalidate a blanket
    # claim that all documented medication exposures have been reconciled.
    for entry in bundle.get("entry",[]):
        r=entry.get("resource") or {}
        if r.get("resourceType")=="MedicationAdministration" and scoped(snap,r):
            meta=r.get("meta") or {}
            if not r.get("id") or not meta.get("versionId") or not meta.get("lastUpdated"):
                complete=False
    for r in snap.current.values():
        if not scoped(snap,r) or r.get("resourceType")!="MedicationAdministration" or r is anchor: continue
        try:
            if r.get('status') in ('not-done','entered-in-error'):
                refs |= validated(snap,context,r)
                continue
            ingredient,first,last,source=exposure(snap,context,r)
            if first>start: continue
            history.add(n.ref(r))
            if last is None:
                doc=snap.exact[context['therapy_receipts'][n.ref(r)]['source']]
                if n.instant(r['meta']['lastUpdated'])<start or n.instant(doc['date'])<start:
                    complete=False  # an old open administration does not prove ongoing exposure at the anchor
            refs |= source
            matched=[g for g in groups if g<=ingredient]
            # Known nonmembers of the official list need independent ingredient
            # verification. A partial combination might instead be coadministered.
            if (ingredient&known) - set().union(*matched): complete=False
            if ingredient-known: complete=False
            if matched:
                contributors=set().union(*matched)
                positives.append((r,contributors,as_days(start-(min(last,start) if last else start))))
                present |= source
        except (KeyError,TypeError,ValueError,ArithmeticError):
            complete=False
    try:
        cover=has_coverage(snap,context,start,history,n.ref(anchor)) if is_actual else set()
    except (KeyError,TypeError,ValueError,ArithmeticError): cover=set()
    out={}
    def put(k,v,source,reason):
        cid=n.contract(rule['facts'][k])
        if cid in snap.enabled:out[cid]=(v,None,sorted(source),reason)
    if positives: put(DRUG,True,present|anchor_refs,"Documented administration contains a §12.8 ingredient or complete same-product combination.")
    elif complete and cover: put(DRUG,False,refs|cover,"Signed, source-linked history to the actual first dose supports no listed exposure.")
    if not positives or not complete or not cover:return out
    refs |= cover
    put(DAYS,float(min(d for _,_,d in positives)),refs,"Shortest elapsed interval from a documented listed drug exposure to the actual first SOT106 dose.")
    ratios=[]
    try:
        for r,ids,days in positives:
            half,extra=half_lives(snap,context,r,ids)
            ratio=float(days/half)
            if not math.isfinite(ratio):return out
            ratios.append(ratio);refs|=extra
    except (KeyError,TypeError,ValueError,ArithmeticError):return out
    put(LIVES,min(ratios),refs,"Minimum elapsed product-specific half-lives with matching administration, route, source and ingredient.")
    return out
