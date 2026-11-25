"""Replay each source criterion's synthetic cases through the FHIR binding and execution path."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from bindings import Snapshot, make_packet, contract
from rules_engine import validate, evaluate
from screen_study import ROOT, FOCAL, HISTORICAL, read, registry, screen

def run_pack(rules,study,digest,source_ids):
    if set(rules)!=set(source_ids):
        raise ValueError((study,"Rule IDs differ from the source inventory",set(rules)^set(source_ids)))
    counts=Counter()
    for cid,rule in rules.items():
        try:
            validate(rule)
            if not rule["cases"]:
                raise ValueError("No synthetic example")
            for case in rule["cases"]:
                one={cid:rule}
                packet=make_packet(one,{cid:case["values"]},study,digest)
                snap=Snapshot(packet["bundle"],packet["context"],study,digest)
                got=evaluate(rule,snap)
                if got["state"]!=case["expected"]:
                    raise AssertionError((case["name"],case["expected"],got["state"],got["reason"]))
                counts[got["state"]]+=1
        except Exception as e:
            raise ValueError((study,cid,str(e))) from e
    return dict(rules=len(rules),cases=sum(counts.values()),outcomes=dict(counts))

def controls():
    study="1479-0032"
    digest=registry()[study]["sha256"]
    spec={"label":"Test measurement","role":"record","scope":"Signed measured score at screening.","kind":"number","unit":"1"}
    rule={"facts":{"score":spec},"expression":{"fact":"score","op":"ge","value":2}}
    def packet(value=2):
        return make_packet({"test":rule},{"test":{"score":value}},study,digest)
    def outcome(p,r=rule):
        return evaluate(r,Snapshot(p["bundle"],p["context"],study,digest))["state"]
    named={}
    def check(name,actual,expected):
        if actual!=expected:raise AssertionError((name,actual,expected))
        named[name]=actual
    check("inclusive boundary",outcome(packet()),"MET")
    check("below boundary",outcome(packet(1)),"NOT_MET")
    p=packet();p["context"]["enabled_contracts"]=[]
    check("disabled mapping",outcome(p),"BINDING_HOLD")
    for name,field,new in [
        ("different patient","subject",{"reference":"Patient/other"}),("different episode","focus",[{"reference":"Condition/other"}]),
        ("future event","effectiveDateTime","2099-01-01T00:00:00Z"),("unsigned source link","derivedFrom",[]),
        ("provisional result","status","preliminary"),("wrong signer","performer",[{"reference":"Practitioner/other"}])]:
        p=packet();p["bundle"]["entry"][-1]["resource"][field]=new
        check(name,outcome(p),"MISSING_DATA")
    p=packet();p["bundle"]["entry"][-1]["resource"]["valueQuantity"]["system"]="urn:other"
    check("incorrect unit namespace",outcome(p),"MISSING_DATA")
    p=packet();p["bundle"]["entry"][-1]["resource"]["valueQuantity"]["value"]=True
    check("boolean masquerading as number",outcome(p),"MISSING_DATA")
    p=packet(); alt=deepcopy(p["bundle"]["entry"][-1]); alt["resource"]["id"]="contradiction";alt["resource"]["valueQuantity"]["value"]=1
    p["bundle"]["entry"].append(alt)
    check("conflicting observations",outcome(p),"MISSING_DATA")
    p=packet();alt=deepcopy(p["bundle"]["entry"][-1]);alt["resource"]["valueQuantity"]["value"]=1;p["bundle"]["entry"].append(alt)
    try:outcome(p)
    except ValueError: check("conflicting version rejected",True,True)
    else:raise AssertionError("Conflicting version escaped validation.")
    p=packet(); p["bundle"]["entry"]=p["bundle"]["entry"][:3]
    check("missing is indeterminate under negation",outcome(p,{**rule,"expression":{"not":rule["expression"]}}),"MISSING_DATA")
    p=packet();check("fact-qualified applicability",outcome(p,{**rule,"applies":{"fact":"score","op":"lt","value":2}}),"NOT_APPLICABLE")
    p=packet();check("explicit unresolved interpretation",outcome(p,{**rule,"expression":{"hold":"Which scope applies?"}}),"AUTHORING_HOLD")
    record=read(ROOT/"rules"/(HISTORICAL+".json"))
    p=make_packet(record["rules"],{},HISTORICAL,registry()[HISTORICAL]["sha256"])
    held=screen(p)
    check("historical protocol cannot screen current patients",set(r["state"] for r in held["criteria"].values())=={"SOURCE_VERSION_HOLD"} and len(held["criteria"])==43,True)
    return named

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-focal",action="store_true",help="Skip the longer two-study retained regression suite.")
    args=parser.parse_args()
    for line in (ROOT/"SHA256SUMS").read_text().splitlines():
        digest,name=line.split("  ",1)
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest: raise ValueError("Checksum mismatch: "+name)
    checked={}
    for study,record in registry().items():
        if study in FOCAL:continue
        source=read(ROOT/"source_criteria"/(study+".json"))
        pack=read(ROOT/"rules"/(study+".json"))
        checked[study]=run_pack(pack["rules"],study,record["sha256"],[c["id"] for c in source["criteria"]])
        if pack.get("supplemental_rules"):
            checked[study]["supplemental"]=run_pack(pack["supplemental_rules"],study,record["sha256"],[r["requirement"] for r in source["supplemental_requirements"]])
    focal=None
    if not args.skip_focal:
        focal=json.loads(subprocess.check_output([sys.executable,"-B",str(ROOT/"previous_focal"/"verify_release.py")]))
    print(json.dumps({"numbered_criteria":sum(len(rows) for rows in read(ROOT/"rules-index.json").values()),"typed_suites":checked,
                      "cross_study_controls":controls(),"retained_focal_suite":focal},indent=2))
if __name__=="__main__":main()
