"""Rebuild the coverage and search plans from the pinned sources and implementation registry."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "modules"))
import assertions
import identity
import philogen
import quantitative
import rec_labs
import retrieve

STUDIES = {
    "106S01": ("SOTIO Biotech", "Separate Part A and Part B. Cohort availability and adolescent authorization are site records."),
    "NEOK001-1": ("NEOK Bio", "Backfill or expansion eligibility depends on the selected cohort and dated site clearance."),
    "REC-1245-101": ("Recursion", "The catalog distinguishes numbered criteria from appendix requirements and site state."),
    "NCT05653388": ("University of Michigan", "An observational leiomyosarcoma biomarker study. Specimen and enrollment procedures are recorded separately."),
    "FOG-001-301": ("Parabilis Medicines", "34 criteria govern initial double-blind entry. Eleven additional criteria govern the open-label extension."),
    "DB-1311-O-1001": ("DualityBio", "Phase 2a uses the shared criteria plus the single applicable cohort among eight cohort-specific inclusions."),
    "PH-L19TNFDOX2": ("Philogen", "Historical protocol v6 only. The upload references v7 but does not contain its full text."),
    "1479-0032": ("Boehringer Ingelheim", "Completely resected, HER2-mutant non-small cell lung cancer. This uploaded study is outside the sarcoma population."),
}
LEVELS = ("rule", "scoped", "component", "mapped")

def read(p):
    return json.loads(p.read_text())

def dump(p, data):
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

def key(study, criterion):
    return study, criterion.removeprefix(study + "-")

def bindings():
    registry = {}
    for r in read(ROOT / "prior_runtime/inventory.json")["criteria"]:
        stage = r["stage"]
        if stage == "authoring_pending":
            continue
        if stage not in ("existing_michigan_query", "tested_research_rule", "tested_with_scoped_holds"):
            raise ValueError(stage)
        scoped = stage=="tested_with_scoped_holds" or r["id"]=="MI-LMS-02"
        entry = "prior_runtime/michigan.pyz" if stage=="existing_michigan_query" else "prior_runtime/screen.py"
        registry[key(r["study"], r["id"])] = ("scoped" if scoped else "rule", entry)
    whole = {"quantitative":list(quantitative.RULES), "assertions":list(assertions.RULES),
             "boehringer":[("1479-0032","E07")], "duality_qtc":[("DB-1311-O-1001","E05")],
             "philogen":[("PH-L19TNFDOX2",c) for c in philogen.RULES]}
    for module, rows in whole.items():
        for s,c in rows:
            k = key(s,c)
            if k in registry:
                raise ValueError(f"Conflicting evaluator {k}")
            registry[k] = ("rule",f"modules/{module}.py")
    components = {}
    for name,s,c,leaf in [("identity",r["study"],r["criterion"],r["fact"]) for r in identity.LEAVES] + [
        ("rec_labs","REC-1245-101","I08",leaf) for leaf in rec_labs.LEAVES]:
        components.setdefault(key(s,c),[]).append(dict(module=f"modules/{name}.py",fact=leaf))
    return registry, components

def build():
    registry, components = bindings()
    coverage, plans, ui, seen = [], [], [], set()
    for s,(name,notice) in STUDIES.items():
        study=read(ROOT/"studies"/(s+".json"))
        assert study["study"]==s
        rows=[]
        for c in study["criteria"]:
            k=key(s,c["id"])
            assert k not in seen and all(c.get(x) for x in ("logic","source_text","evidence","locator","polarity")),k
            seen.add(k)
            leaves=components.get(k,[])
            level,module=registry.get(k,("component" if leaves else "mapped",None))
            case={"study":s,"criterion":c["id"],"level":level,"rule_entry":module,"tested_components":leaves}
            coverage.append(case)
            p=retrieve.plan(study,c["id"],"SYN-001")
            assert p["queries"],k
            plans.append(p)
            info={"rule":"Criterion evaluator replayed on synthetic records.", "scoped":"Criterion evaluator replayed on synthetic records. Specific interpretation or evidence branches have explicit holds.",
                  "component":"Individual predicates were tested. The complete criterion has no verified evaluator in this release.",
                  "mapped":"Evidence sources and patient-scoped retrieval queries are specified. The complete criterion has no verified evaluator in this release."}[level]
            if module: info+=" Implementation: "+module+"."
            if leaves: info+=f" {len(leaves)} separately tested evidence component(s)."
            title=" ".join(c["logic"].split()).split(". ")[0].rstrip(".")
            if len(title)>74: title=title[:73].rsplit(" ",1)[0]+"…"
            rows.append({"id":c["id"],"label":title,"level":level,"coverage":info,**{k:c[k] for k in ("polarity","evidence","remaining","logic","locator")}})
        ui.append({"study":s,"name":name,"version":study["version"],"notice":notice,"criteria":rows})
    assert not (set(registry)|set(components))-seen
    assert len(seen)==272
    return coverage,plans,{"studies":ui}

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ui",type=Path)
    args=parser.parse_args()
    coverage,plans,ui=build()
    dump(ROOT/"coverage.json",coverage)
    dump(ROOT/"retrieval_plans.json",plans)
    if args.ui: dump(args.ui,ui)
    print(json.dumps(Counter(r["level"] for r in coverage)))
