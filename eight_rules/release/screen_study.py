"""PocketMD deterministic research screening across eight uploaded protocols."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from bindings import Snapshot, make_packet, result
from rules_engine import evaluate

ROOT=Path(__file__).resolve().parent
FOCAL={"106S01","NCT05653388"}
HISTORICAL="PH-L19TNFDOX2"
VERSION_QUESTION="Obtain the complete site-effective Philogen protocol (the site approval cites v7) and its effective date. The uploaded v6 supports historical replay only."

def read(path):
    return json.loads(path.read_text())

def registry():
    return read(ROOT/"sources.json")

def get_pack(study):
    if study not in registry() or study in FOCAL:
        raise ValueError("Select a supported typed rule pack.")
    return read(ROOT/"rules"/(study+".json"))

def case_packet(study,cid,index):
    pack=get_pack(study)
    all_rules={**pack["rules"],**pack.get("supplemental_rules",{})}
    rule=all_rules[cid]
    if index<1 or index>len(rule["cases"]):
        raise ValueError("Use a 1-based case index from the rule's cases.")
    case=rule["cases"][index-1]
    packet=make_packet(all_rules,{cid:case["values"]},study,registry()[study]["sha256"])
    if study==HISTORICAL:
        packet["context"]["purpose"]="historical_replay"
    return packet

def screen(packet):
    ctx=packet["context"]
    study=ctx["study"]
    records=registry()
    if study not in records or ctx.get("protocol_sha256")!=records[study]["sha256"]:
        raise ValueError("Unknown study or protocol version. Load its source and approved rules before screening.")
    if study in FOCAL:
        entry=ROOT/"previous_focal"/"screen_study.py"
        run=subprocess.run([sys.executable,"-B",str(entry),"--packet","-"],input=json.dumps(packet),
                           text=True,capture_output=True,timeout=25)
        if run.returncode:
            raise ValueError(run.stderr.strip())
        return json.loads(run.stdout)
    pack=get_pack(study)
    rules=pack["rules"]
    out={"study":study,"protocol_sha256":records[study]["sha256"],"patient":ctx["patient"],"as_of":ctx["as_of"]}
    if study==HISTORICAL and ctx.get("purpose")!="historical_replay":
        out.update(mode="historical_version_block",criteria={k:result("SOURCE_VERSION_HOLD",VERSION_QUESTION) for k in rules})
        return out
    snapshot=Snapshot(packet["bundle"],ctx,study,records[study]["sha256"])
    out.update(mode="historical_replay" if study==HISTORICAL else "normalized_research",criteria={
        cid:evaluate(rule,snapshot) for cid,rule in rules.items()})
    if pack.get("supplemental_rules"):
        out["supplemental"]={cid:evaluate(rule,snapshot) for cid,rule in pack["supplemental_rules"].items()}
    return out

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list",action="store_true",help="List studies, source versions and bundled demos.")
    group.add_argument("--packet",help="FHIR collection and screening context, or - for stdin.")
    group.add_argument("--demo",help="Run one named synthetic packet.")
    group.add_argument("--case",nargs=3,metavar=("STUDY","RULE","NUMBER"),help="Run a numbered synthetic test from a typed rule pack.")
    group.add_argument("--rule",nargs=2,metavar=("STUDY","RULE"),help="Inspect a cited rule, evidence requirements and test results.")
    args=parser.parse_args()
    if args.list:
        data={"studies":list(registry()),"demos":sorted(p.stem for p in (ROOT/"examples").glob("*.json"))}
    elif args.rule:
        study,cid=args.rule
        index=read(ROOT/"rules-index.json")[study]
        data=index[cid] if cid in index else get_pack(study)["supplemental_rules"][cid]
    elif args.case:
        study,cid,num=args.case
        packet=case_packet(study,cid,int(num))
        record=screen(packet)
        data=record["criteria"][cid] if cid in record["criteria"] else record["supplemental"][cid]
    elif args.demo:
        names={p.stem:p for p in (ROOT/"examples").glob("*.json")}
        if args.demo not in names:
            parser.error("Unknown bundled example.")
        data=screen(read(names[args.demo]))
    else:
        data=screen(json.load(sys.stdin) if args.packet=="-" else read(Path(args.packet)))
    print(json.dumps(data,indent=2,ensure_ascii=False,allow_nan=False))
if __name__=="__main__":
    try:
        main()
    except (KeyError,ValueError,TypeError,AttributeError,OverflowError) as exc:
        sys.exit("Unable to evaluate the research input: "+str(exc))
