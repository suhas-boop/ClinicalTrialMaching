"""PocketMD offline research screening for the supplied Michigan and SOTIO amendments."""
import argparse
import importlib
import json
from pathlib import Path
import sys

from normalized import HASH, ROOT, Snapshot, evaluate
from legacy.bridge import run_michigan, run_sotio

MICHIGAN = "NCT05653388"
SOTIO = "106S01"
MICHIGAN_HASH = "f920e02d5b194d147a76e2c60e94884f599d3982cda8e7ecfaee2a10a5f3f08b"
ADAPTERS = ("entry_adapter","organ_adapter","heart_adapter","therapy_adapter")

def read(path): return json.loads(path.read_text())

def evaluate_normalized(rules,bundle,context):
    snap=Snapshot(bundle,context)
    for module in ADAPTERS:
        found=importlib.import_module(module).derive(rules,bundle,context)
        if set(snap.native).intersection(found): raise ValueError("Two adapters claim the same evidence contract.")
        snap.native.update(found)
    criteria={}
    for cid,rule in rules.items():
        item=evaluate(rule,snap)
        item["resources"]={r:snap.exact[r] for r in item['evidence'] if r in snap.exact}
        criteria[cid]=item
    return criteria

def screen(packet):
    ctx=packet["context"]
    bundle=packet["bundle"]
    study=ctx["study"]
    if not isinstance(bundle,dict) or bundle.get("resourceType")!="Bundle" or bundle.get("type")!="collection":
        raise ValueError("Supply a normalized FHIR collection Bundle.")
    if study==MICHIGAN:
        if ctx.get("protocol_sha256")!=MICHIGAN_HASH: raise ValueError("Michigan protocol fingerprint mismatch.")
        return run_michigan(bundle,ctx["patient"],ctx["episode"],ctx["as_of"])
    if study!=SOTIO or ctx.get("protocol_sha256")!=HASH: raise ValueError("Unsupported study or protocol fingerprint.")
    rules=read(ROOT/"sotio_rules.json")
    new=evaluate_normalized(rules,bundle,ctx)
    out=run_sotio(bundle,ctx["patient"],ctx["encounter"],ctx["as_of"],timezone_name=ctx.get("site_zone","UTC"),
                  trusted_signers=ctx.get("trusted_signers"),onboarding=ctx.get("onboarding"))
    if set(new)&set(out['criteria']): raise ValueError("Overlapping criterion implementations.")
    out['criteria']={**out['criteria'],**new}
    if len(out['criteria'])!=42: raise ValueError("Incomplete SOTIO release registry.")
    out['criteria']=dict(sorted(out['criteria'].items(), key=lambda x:(x[0][0]!='I',x[0])))
    return out

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet",help="JSON containing context and bundle. Use - for stdin.")
    parser.add_argument("--demo", help="A named example from examples/.")
    parser.add_argument("--list",action="store_true")
    args=parser.parse_args()
    if args.list:
        print(json.dumps(sorted(x.stem for x in (ROOT/"examples").glob("*.json"))));return
    if bool(args.packet)==bool(args.demo): parser.error("Choose one of --packet and --demo.")
    if args.demo:
        if args.demo not in {p.stem for p in (ROOT/"examples").glob("*.json")}: parser.error("Unknown demo.")
        p=read(ROOT/"examples"/(args.demo+".json"))
    else: p=json.load(sys.stdin) if args.packet=="-" else read(Path(args.packet))
    print(json.dumps(screen(p),indent=2,ensure_ascii=False,allow_nan=False))

if __name__=="__main__":
    try: main()
    except (KeyError,ValueError,TypeError,AttributeError,OverflowError) as ex:
        sys.exit("Unable to screen this research packet: "+str(ex))
