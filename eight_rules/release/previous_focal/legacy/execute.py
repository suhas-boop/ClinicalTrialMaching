"""Run a specific pinned backend in its own interpreter so its module names cannot collide."""
import json
import re
import sys
import zipimport
from datetime import date
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
PINNED = ROOT / "pinned"
MICHIGAN = "NCT05653388"
SOTIO = "106S01"


def indexed_resources(bundle):
    result={}
    for entry in bundle["entry"]:
        resource=entry["resource"]
        version=resource.get("meta",{}).get("versionId")
        if version:
            ref=f"{resource['resourceType']}/{resource['id']}/_history/{version}"
            result[ref]=resource
    return result


def with_resources(result,index):
    return {**result,"resources":{ref:index[ref] for ref in result["evidence"] if ref in index}}


def leaves(node):
    if isinstance(node,str):
        yield node
    else:
        for child in next(iter(node.values())):
            yield from leaves(child)


def michigan(packet, demo=False, packet_only=False):
    archive=PINNED / "michigan.pyz"
    sys.path.insert(0,str(archive))
    frozen={}
    # Execute the exact frozen entry module without invoking its command-line parser.
    frozen["__name__"]="pinned_michigan"
    exec(zipimport.zipimporter(str(archive)).get_code("__main__"),frozen)
    with ZipFile(archive) as z:
        catalog, rules, charts=[json.loads(z.read("data/"+k+".json")) for k in ("catalog","rules","charts")]
    if demo:
        label=packet["label"]
        chart=next((c for c in charts if c["id"]==label),None)
        if chart is None:raise ValueError("Unknown Michigan demo scenario.")
        entries=frozen["bundle_entries"](chart,"demo-",catalog)
        for entry in entries:entry["resource"]["meta"]={"versionId":"1"}
        bundle=dict(resourceType="Bundle",type="collection",entry=entries)
        patient,episode,as_of=f"Patient/demo-{label}-p",f"Condition/demo-{label}-current",frozen["DATE"]
    else:
        bundle=packet["bundle"]
        patient=frozen["reference"]("Patient",packet["patient"])
        episode=frozen["reference"]("Condition",packet["episode"])
        as_of=packet["as_of"]
    if not isinstance(as_of,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",as_of):
        raise ValueError("Michigan requires an explicit calendar-day as_of.")
    date.fromisoformat(as_of)
    if packet_only:
        return {"bundle":bundle,"patient":patient,"episode":episode,"as_of":as_of}
    data=frozen["query"](frozen["BundleReader"](bundle),patient,episode,as_of,catalog,rules,"all",True)
    registry=indexed_resources(bundle)
    criteria={}
    for criterion,trace in data["rules"].items():
        state={**data["outcomes"],**data["holds"]}[criterion]
        keys=list(leaves(trace["expression"]))
        facts={k:data["facts"][k] for k in keys}
        decisive=[f["reason"] for f in facts.values() if f["outcome"]==state]
        if state=="MET":
            reason="The indexed episode and documented evidence satisfy the criterion."
        elif state=="NOT_MET":
            reason="The documented evidence fails at least one required condition."
        else:
            reason=" ".join(dict.fromkeys(decisive)) or "Resolve the evidence for the indexed episode."
        refs=sorted({r for f in facts.values() for r in f["evidence"]})
        criteria[criterion]=with_resources(dict(state=state,reason=reason,evidence=refs,
            facts=facts,expression=trace["expression"],source=trace["source"]),registry)
    return {k:data[k] for k in ("study","patient","episode","as_of","catalog_version","protocol_sha256","requests")} | {"criteria":criteria}


def sotio(packet):
    sys.path.insert(0,str(PINNED))
    import assertions
    import screen
    from amendments import corrected_criteria
    bundle=packet["bundle"]
    patient,visit=packet["patient"].removeprefix("Patient/"),packet["encounter"].removeprefix("Encounter/")
    cutoff=packet["as_of"]
    if not cutoff: raise ValueError("Provide an explicit screening cutoff.")
    if not all(re.fullmatch(r"[a-zA-Z0-9.-]{1,64}",s) for s in (patient,visit)):
        raise ValueError("Provide a patient and encounter ID.")
    zone=packet.get("timezone_name") or "UTC"
    data=screen.run(SOTIO,bundle,patient,visit,cutoff,timezone_name=zone,onboarding=packet.get("onboarding"))
    results={key.removeprefix(SOTIO+"-"):result for key,result in data["criteria"].items() if key in screen.RULES}
    results.update(corrected_criteria(bundle,patient,visit,cutoff,zone,data.get("simulated_schedule")))
    key=SOTIO+"-E13"
    results["E13"]=assertions.evaluate(bundle,{"study":SOTIO,"criterion":key,"protocol_sha256":data["protocol_sha256"],
                   "phase":"screening","patient":"Patient/"+patient,"encounter":"Encounter/"+visit,"as_of":cutoff,
                   "trusted_signers":packet.get("trusted_signers") or {}})
    resources=indexed_resources(bundle)
    return {k:data[k] for k in ("study","patient","as_of","protocol_sha256","catalog")} | {"encounter":"Encounter/"+visit,
        **({"simulated_schedule":data["simulated_schedule"]} if data.get("simulated_schedule") else {}),
        "criteria":{k:with_resources(v,resources) for k,v in results.items()}}


if __name__=="__main__":
    try:
        operation=sys.argv[1]
        packet=json.load(sys.stdin)
        result=sotio(packet) if operation=="sotio" else michigan(packet, operation in {"michigan-demo","michigan-packet"}, operation=="michigan-packet")
        print(json.dumps(result,allow_nan=False))
    except (KeyError,IndexError,ValueError,TypeError,ArithmeticError) as exc:
        sys.exit("The normalized snapshot could not be evaluated: "+str(exc))
