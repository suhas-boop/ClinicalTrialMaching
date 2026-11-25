"""Rebuild the 12-row original-source comparison and frozen-input retrieval replay."""
import argparse
import base64
import csv
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
DATA = HERE.parent
sys.path.insert(0,str(DATA))
from review_replay import contract, make_packet, roles
from recover_records import recover

# Reviewed against both original topic description and summary. Each label describes
# a record to look up for this episode. The wound and surgery pairs share a lookup.
PLAN = {
    25: ("hypertension assessment", "Documented severe, malignant or secondary hypertension"),
    81: ("infection assessment and study visit dates", "Severity and activity of infection relative to screening and baseline"),
    115: ("wound etiology assessment", "Whether leishmaniasis or an insect bite caused this ulcer"),
    116: ("wound etiology assessment", "Whether a burn caused this ulcer"),
    239: ("gynecologic history", "Documented menopausal status"),
    336: ("consent and proxy records", "Documented consent disposition and authorized representative"),
    366: ("surgical consultation and operative note", "Abdominal trauma requiring open laparotomy with primary closure"),
    367: ("surgical consultation and operative note", "Acute surgical abdomen requiring open laparotomy with primary closure"),
    385: ("medication tolerance assessment", "Ability to take and retain oral medication"),
    460: ("head CT report and neurologic assessment", "Qualifying CT finding with corresponding total or motor GCS"),
    850: ("longitudinal asthma symptom history", "Weekly frequency of asthma exacerbations"),
    890: ("admission cognitive assessment", "Cognitive impairment established by screening at hospital admission"),
}
URLS = {"2014":"https://www.trec-cds.org/topics2014.xml",
        "2015":"https://trec.nist.gov/data/clinical/topics-2015-A.xml"}


def load(p):
    return json.loads(p.read_text())


def run(paths, dest):
    docs = {year: ET.parse(path).getroot() for year, path in paths.items()}
    audit = {int(r["annotation_id"]):r for r in csv.DictReader((DATA/"round3/prior_49_audit.csv").open())
             if r["audit_category"].startswith("Partial evidence")}
    if set(audit) != set(PLAN):
        raise ValueError("The audited cohort has changed.")
    out, traces = [], {}
    for folder in (DATA, DATA/"round2"):
        cohort = load(folder/"blind.json")
        definitions, abstracted = load(folder/"rules.json"), load(folder/"facts.json")
        for r in cohort:
            cid = r["annotation_id"]
            if cid not in audit:
                continue
            pid, trial, k = r["patient_id"], r["trial_id"], str(cid)
            year, num = re.fullmatch(r"sigir-(201[45])(\d+)",pid).groups()
            topic = next(n for n in docs[year] if int(n.attrib["number"]) == int(num))
            desc = " ".join(topic.findtext("description").split())
            summary = " ".join(topic.findtext("summary").split())
            if not desc or not summary:
                raise ValueError("Missing topic text")
            lines = dict((int(n), s) for n,s in re.findall(r"^(\d+)\. (.*)$",r["note"],re.M))
            rule = definitions[k]
            for name,spec in rule["facts"].items():
                spec["role"] = roles.get(name,spec["role"])
            facts = {n:v for n,v in abstracted.get(pid,{}).items() if n in rule["facts"]}
            version = hashlib.sha256(json.dumps(sorted((x["criterion_type"],x["criterion_text"])
                                     for x in cohort if x["trial_id"]==trial)).encode()).hexdigest()
            packet = make_packet({k:rule},{k:{n:v[0] for n,v in facts.items()}},trial,version,patient=pid)
            for e in packet["bundle"]["entry"]:
                doc = e["resource"]
                if doc["resourceType"]=="DocumentReference":
                    n = next(n for n in facts if doc["id"]=="src-"+contract(rule["facts"][n]))
                    text = "\n".join(lines[i] for i in facts[n][1])
                    doc["content"][0]["attachment"].update(title=pid, data=base64.b64encode(text.encode()).decode())
            empty = {"resourceType":"Bundle", "type":"collection", "entry":[]}
            result = recover({k:rule},packet,empty,trial,version)
            traces[k] = result
            rec, qualifier = PLAN[cid]
            out.append(dict(annotation_id=cid,patient_id=pid,trial=trial,criterion=r["criterion_text"],
                     case_source=URLS[year],topic_number=num,original_text_sha256=hashlib.sha256((desc+"\n"+summary).encode()).hexdigest(),
                     original_description_present_verbatim=" ".join(lines.values()).startswith(desc),
                     existing_evidence_and_gap=audit[cid]["rationale"],detail_required=qualifier,
                     first_chart_lookup=rec,lookup_group=pid+"/"+rec,verified_new_primary_record=0,
                     before=result["transitions"][k]["before"],after=result["transitions"][k]["after"]))
    out.sort(key=lambda row:row["annotation_id"])
    if len(out)!=len(PLAN):
        raise ValueError("Missing or duplicate case.")
    dest.mkdir(exist_ok=True,parents=True)
    with (dest/"PocketMD_12_Source_Recovery.csv").open("w",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(out[0]))
        writer.writeheader()
        writer.writerows(out)
    (dest/"public_replay.json").write_text(json.dumps(traces,indent=2,sort_keys=True)+"\n")
    receipt = {"criteria":len(out),"original_topics":len({r["patient_id"] for r in out}),
               "initial_chart_lookups":len({r["lookup_group"] for r in out}),
               "new_definite":sum(len(x["new_evidence_backed_decisions"]) for x in traces.values()),
               "states":{s:sum(r["after"]==s for r in out) for s in sorted({r["after"] for r in out})},
               "source_sha256":{year:hashlib.sha256(p.read_bytes()).hexdigest() for year,p in paths.items()}}
    (dest/"source_receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    print(json.dumps(receipt))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--topics-2014",type=Path,required=True)
    p.add_argument("--topics-2015",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    run({"2014":args.topics_2014,"2015":args.topics_2015},args.out)
