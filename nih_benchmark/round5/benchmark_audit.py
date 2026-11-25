"""Post-label development replay. No expert information enters evaluate_vignette."""
import ast
from collections import Counter
import csv,json,sys
from pathlib import Path
BASE=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(BASE/"criterion_workbench"))
from registry_context import packet as registry_packet
from screen_vignette import evaluate_vignette

# Reviewed distinctions between the cited statements and the governing fact.
review={
46:("retrieve_record","Chest radiograph shows a lung mass and head CT shows a brain lesion. Retrieve the chest CT and its date."),
138:("retrieve_record","Current medication list gives two named drugs. Review prior as well as current antipsychotic exposure."),
179:("retrieve_record","The documented catheter is arterial. Verify a separate history of central venous access."),
185:("retrieve_record","Hypotension and examination findings are recorded. Look for a documented diagnosis of shock or ARDS."),
186:("retrieve_record","Tachycardia is described. Retrieve the measured heart rate for this episode."),
187:("retrieve_record","Tachypnea is described. Retrieve the measured respiratory rate, arterial gas or ventilation record."),
322:("retrieve_record","Demographic description alone does not establish the two reproductive facts in the released rule. Retrieve an applicable assessment or an authorized applicability rule."),
437:("retrieve_record","Symptoms and home oxygen are documented. Obtain the classified COPD exacerbation assessment."),
454:("retrieve_record","Adult age and acute bleeding are present. Imaging and an emergency operation are distinct events. Obtain the operative record."),
544:("protocol_review","Which documented conditions or severity measures meet this trial's severe cardiac condition exclusion? The note includes a remote infarction."),
632:("retrieve_record","Future willingness to consent does not establish the person's ability to provide written consent. Check the consent assessment."),
640:("investigator","If no recorded assessment exists, does this pain meet the protocol's typical chest pain definition? Its characteristics are documented."),
671:("retrieve_record","Mood symptoms are documented. Retrieve a diagnosis specifying unipolar major depression."),
965:("retrieve_record","This CBC establishes current cytopenias. Review the record for a known history as required by this criterion."),
}
holds={
130:"Does any one listed diagnosis suffice, or must the three diagnoses coexist?",
184:"Who determines whether another situation is inappropriate, and how is the determination documented?",
706:"Does the pelvic congestion criterion require every listed symptom, any one symptom, or an independently documented diagnosis?",
737:"Does a disorder in any one listed gland system suffice, or must all three systems be involved?",
}
def load(path):
    return json.loads(path.read_text())

def main():
    r3=HERE.parent/"round3"
    old={int(r["annotation_id"]):r for r in csv.DictReader((r3/"results.csv").open()) if r["mode"]=="automatic"}
    rules=load(r3/"rules.json")
    outcomes=[]; audit=[]; registry=[]; work={}
    for case in load(r3/"blind.json"):
        i=case["annotation_id"];r=old[i]
        v=evaluate_vignette(rules[str(i)],case["patient_id"],case["trial_id"],case["criterion_text"],case["note"])
        outcomes.append({"annotation_id":i,"previous":r["state"],"current":v["state"],"expert":r["expert_state"],
                         "sentences":v["sentences"],"extracted":v["extracted"]})
        for q in v["requests"]:
            work[q["id"]]=q["route"]
        if r["expert_state"] not in {"MET","NOT_MET"} or r["state"] in {"MET","NOT_MET"}:continue
        reason="No physician sentence cited. Retrieve the specific evidence requested by the rule."
        route, rationale=review.get(i,("retrieve_record",reason))
        if i in holds:
            raw=(HERE/"registry"/(case["trial_id"]+".json")).read_bytes()
            detail=registry_packet(case["trial_id"],case["criterion_text"],raw)
            registry.append({k:v for k,v in detail.items() if k!="sections"}|{"id":i,"question":holds[i]})
            route,rationale="protocol_review",holds[i]
        audited=i in review or i in holds
        audit.append(dict(annotation_id=i,trial=case["trial_id"],criterion=case["criterion_text"],
                          previous=r["state"],replay=v["state"],cited_sentences=r["expert_sentences"],
                          review_depth="source reviewed" if audited else "uncited; routing only",
                          suggested_followup=route,rationale=rationale))
    (HERE/"registry_review.json").write_text(json.dumps(registry,indent=2))
    (HERE/"replay.json").write_text(json.dumps(outcomes,indent=2))
    with (HERE/"PocketMD_33_Case_Audit.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=audit[0]);w.writeheader();w.writerows(audit)
    print(json.dumps({"rows":len(outcomes),"agreement_on_definite":sum(r["current"]==r["expert"] and r["current"] in {"MET","NOT_MET"} for r in outcomes),
        "changed":sum(r["previous"]!=r["current"] for r in outcomes),"audited_open":len(audit),
        "audit_routes":dict(Counter(r["suggested_followup"] for r in audit)),
        "live_engine_requests_for_63":dict(Counter(work.values()))},indent=2))
if __name__=="__main__":main()
