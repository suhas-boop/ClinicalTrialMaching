"""Replay synthetic checks, verify one query plan per criterion, and optionally authenticate uploaded sources."""
import argparse
from collections import Counter
from hashlib import sha256
import importlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

from catalog import ROOT, build, dump, read

def command(args):
    return json.loads(subprocess.check_output([sys.executable,"-B",*map(str,args)],cwd=ROOT))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir",type=Path,help="Directory containing the original eight uploaded ZIPs.")
    parser.add_argument("--write-receipt",type=Path)
    args=parser.parse_args()
    coverage,plans,_=build()
    assert coverage==read(ROOT/"coverage.json") and plans==read(ROOT/"retrieval_plans.json"),"Saved catalog or plans differ from rebuild."
    specs=read(ROOT/"sources.json")
    assert set(specs)=={r["study"] for r in coverage} and len(specs)==8
    verified=[]
    for s,source in specs.items():
        d=read(ROOT/"studies"/(s+".json"))
        for k in ("protocol_sha256","source_sha256"):
            if d.get(k): assert d[k]==source["sha256"],s
        if args.source_dir:
            with zipfile.ZipFile(args.source_dir/source["archive"]) as z:
                assert sha256(z.read(source["protocol"])).hexdigest()==source["sha256"],s
            verified.append(s)
    outputs={"four-study historical regression":command(["prior_runtime/verify.py"])}
    for name in ("retrieve","quantitative","assertions","duality_qtc","philogen","boehringer","identity","rec_labs"):
        outputs[name]=importlib.import_module(name).run_checks()
    outputs["per-criterion synthetic candidate retrieval"]=importlib.import_module("replay_retrieval").run_checks()
    mi=[]
    for scenario,expected in read(ROOT/"prior_runtime/michigan_expected.json").items():
        result=command(["prior_runtime/michigan.pyz","--demo",scenario])
        assert not set(result["outcomes"]).intersection(result["holds"]),scenario
        dispositions={**result["outcomes"], **result["holds"]}
        for i,want in enumerate(expected,start=1):
            k=f"MI-LMS-{i:02}"
            mi.append({"criterion":k,"case":scenario,"expected":want,"actual":dispositions[k]})
    outputs["Michigan full fixture replay (overlaps historical coverage)"]=mi
    counts={}
    for name,cases in outputs.items():
        failures=[r for r in cases if r["actual"]!=r["expected"]]
        if failures: raise ValueError((name,failures))
        counts[name]=len(cases)
    receipt={"original_protocol_hashes_verified":verified,"study_count":len(specs),"criteria":len(coverage),
             "criteria_with_query":sum(bool(p['queries']) for p in plans),"coverage":dict(Counter(x['level'] for x in coverage)),
             "passed_by_suite":counts,"testing":"Synthetic engineering checks, including overlapping regression scenarios."}
    if args.write_receipt: dump(args.write_receipt,{"summary":receipt,"cases":outputs})
    print(json.dumps(receipt,indent=2))
if __name__=="__main__":
    main()
