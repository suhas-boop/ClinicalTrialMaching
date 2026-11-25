"""Replay the published first-pass states and test the two signed-source amendments."""
import json
import subprocess
import sys
from pathlib import Path

from bridge import MICHIGAN, ROOT, SOTIO, michigan_demo, run_michigan, run_sotio
from generate import PINNED, T, check_prescreen, concept, demo_packet, link, record
from copy import deepcopy


def clinical_anchor(packet, date, actual=False):
    bundle = packet["bundle"]
    record(bundle, "DocumentReference", "schedule", subject=link("Patient/demo"), status="current", date=T)
    record(bundle, "Observation", "cycle", subject=link("Patient/demo"), encounter=link("Encounter/screen"),
           code=concept("urn:pocketmd:research:sotio-milestone", "C1D1-actual" if actual else "C1D1-planned"),
           status="final", issued=T, effectiveDateTime=T, valueDateTime=date,
           derivedFrom=[link("DocumentReference/schedule/_history/1")])
    packet.pop("onboarding",None)


def verify():
    replays=json.loads((ROOT/"legacy_replays.json").read_text())
    expected=json.loads((PINNED/"michigan_expected.json").read_text())
    count=0
    for label, states in expected.items():
        record=michigan_demo(label)
        assert record==replays[MICHIGAN][label],label
        assert [record["criteria"][f"MI-LMS-0{i}"]["state"] for i in range(1,4)]==states,label
        count+=3
    sample_packet=json.loads((ROOT/"michigan_demo.json").read_text())
    assert run_michigan(**sample_packet)==replays[MICHIGAN]["all-met"]
    for study in replays.values():
        for replay in study.values():
            for row in replay["criteria"].values():
                assert set(row['evidence'])==set(row['resources'])
                for ref,resource in row["resources"].items():
                    assert ref==resource["resourceType"]+"/"+resource["id"]+"/_history/"+resource["meta"]["versionId"]
    for filename,label in (("sotio_demo.json","fresh-biopsy"),("sotio_archive.json","archival-when-fresh-feasible")):
        pkt=json.loads((ROOT/filename).read_text()); result=run_sotio(**pkt)
        assert result==replays[SOTIO][label]
        assert len(result["criteria"])==15
        for k,r in result['criteria'].items():
            expect="NOT_MET" if k=="E04" else ("AUTHORING_HOLD" if k=="I06" and label.startswith("archival") else "MET")
            assert r["state"]==expect,(k,r)
    detail=[]
    def check(label,packet,key,state,extra=None):
        result=run_sotio(**packet)["criteria"][key]
        assert result['state']==state,(label,result['state'],result['reason'])
        if extra:assert extra(result),label
        detail.append(dict(case=label,criterion=key,expected=state,actual=result['state']))
    def obs(packet,key):
        return check_prescreen.resource(packet['bundle'],key)
    b=demo_packet(); check("explicit serum specimen",b,"I12","MET",lambda r:'Specimen/serum/_history/1' in r['evidence'])
    for name,edit in [
        ("plasma",lambda p:obs(p,'serum')['type']['coding'][0].update(code="PLAS")),
        ("mixed specimen",lambda p:obs(p,'serum')['type']['coding'].append({'system':'http://terminology.hl7.org/CodeSystem/v2-0487','code':'PLAS'})),
        ("unverified version",lambda p:obs(p,'albumin').update(specimen=link('Specimen/serum/_history/2'))),
        ("missing link",lambda p:obs(p,'albumin').pop('specimen')),
        ("wrong patient",lambda p:obs(p,'serum').update(subject=link('Patient/someone-else')))]:
        p=deepcopy(b);edit(p);check("albumin: "+name,p,"I12","MISSING_DATA")
    for days,state in [(5,"MET"),(6,"NOT_MET")]:
        p=deepcopy(b);clinical_anchor(p,"2026-11-19",True)
        obs(p,"rbc-review")["valueDateTime"]=f"2026-11-{days:02d}T09:00:00Z"
        check("last RBC transfusion "+str(19-days)+" days before actual C1D1",p,"E04",state,
              lambda r:r["schedule_basis"]["basis"]=="documented_actual" and "DocumentReference/schedule/_history/1" in r["evidence"])
    p=deepcopy(b);clinical_anchor(p,"2026-11-26")
    check("planned C1D1 from the documented screening schedule",p,"I08","MET",lambda r:r["schedule_basis"]["basis"]=="documented_plan")
    check("planned C1D1 applied to the serum albumin window",p,"I12","MET")
    p=deepcopy(b);clinical_anchor(p,"2026-11-26",True)
    check("future actual C1D1 rejected",p,"E04","MISSING_DATA")
    p=deepcopy(b);clinical_anchor(p,"2026-11-26");obs(p,"schedule").update(subject=link("Patient/other"))
    check("wrong-patient scheduling document rejected",p,"I08","MISSING_DATA")
    p=deepcopy(b);p.pop("onboarding")
    check("missing cycle date",p,"I12","MISSING_DATA")
    p=deepcopy(b);obs(p,"investigator")['item'][0]['answer'][0]['valueBoolean']=True
    check("forged E13 response rejected",p,"E13","MISSING_DATA")
    p=deepcopy(b);obs(p,"agreement")["item"][0]["answer"][0]["valueBoolean"]=False
    check("participant declines",p,"I07","NOT_MET")
    regression=json.loads(subprocess.check_output([sys.executable,"-B",str(PINNED/"verify.py")]))
    assert len(regression)==227 and all(row['expected']==row['actual'] for row in regression)
    import assertions
    signed=assertions.run_checks()
    signed=[r for r in signed if r['study']==SOTIO and r['criterion']=='106S01-E13']
    assert signed and all(r['expected']==r['actual'] for r in signed)
    return {"michigan_frozen_expectations":count,"michigan_scenarios":len(expected),"sotio_15_criteria_2_clinical_variants":30,
            "pinned_four_study_regressions_includes_overlap":len(regression),"pinned_sotio_e13_signed_controls":len(signed),
            "sotio_additional_bridge_controls":detail}


if __name__=="__main__": print(json.dumps(verify(),indent=2))
