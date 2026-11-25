"""Run source-pinned expectation cases and isolate normalization errors from patient outcomes."""
import json
from copy import deepcopy
from pathlib import Path
from normalized import ROOT, Snapshot, contract, evaluate, make_packet

def run():
    rules=json.loads((ROOT/"sotio_rules.json").read_text())
    cases=json.loads((ROOT/"sotio_cases.json").read_text())
    receipts=[]
    def check(cid,name,packet,expected):
        outcome=evaluate(rules[cid],Snapshot(packet["bundle"],packet["context"]))
        if outcome['state']!=expected:
            raise ValueError((cid,name,expected,outcome['state'],outcome['reason']))
        return dict(criterion=cid,name=name,expected=expected,actual=outcome['state'])
    for case in cases:
        cid=case['criterion'];packet=make_packet(rules,{cid:case['values']})
        receipts.append(check(cid,case['name'],packet,case['expected']))
    by_id={cid:{r["expected"] for r in receipts if r["criterion"]==cid} for cid in rules}
    assert all({"MET","NOT_MET"}.issubset(states) for states in by_id.values())
    cid="E17"; fact=rules[cid]['facts']['heart_rate']
    base=make_packet(rules,{cid:{"heart_rate":50}})
    def last(p):return p["bundle"]["entry"][-1]["resource"]
    def src(p):return p["bundle"]["entry"][-2]["resource"]
    def case(name,edit,state):
        p=deepcopy(base);edit(p);receipts.append(check(cid,name,p,state))
    case("Unregistered mapping",lambda p:p["context"]["enabled_contracts"].remove(contract(fact)),"BINDING_HOLD")
    case("Wrong subject",lambda p:last(p).update(subject={"reference":"Patient/other"}),"MISSING_DATA")
    case("Wrong encounter",lambda p:last(p).update(encounter={"reference":"Encounter/other"}),"MISSING_DATA")
    case("Wrong disease episode",lambda p:last(p).update(focus=[{"reference":"Condition/other"}]),"MISSING_DATA")
    case("Wrong unit",lambda p:last(p)["valueQuantity"].update(code="mg"),"MISSING_DATA")
    case("Untrusted source author",lambda p:src(p).update(author=[{"reference":"Organization/different"}]),"MISSING_DATA")
    case("Source for different person",lambda p:src(p).update(subject={"reference":"Patient/other"}),"MISSING_DATA")
    case("Imprecise clinical date",lambda p:last(p).update(effectiveDateTime="2026-05"),"MISSING_DATA")
    case("Future measurement",lambda p:last(p).update(effectiveDateTime="2031-06-01T00:00:00Z"),"MISSING_DATA")
    case("Unversioned source",lambda p:last(p).update(derivedFrom=[{"reference":"DocumentReference/unknown"}]),"MISSING_DATA")
    def competing(p):
        obs=deepcopy(last(p));obs["id"]="other-reading";obs["valueQuantity"]["value"]=49
        p["bundle"]["entry"].append({"resource":obs})
    case("Conflicting source records",competing,"MISSING_DATA")
    return receipts
if __name__=="__main__":
    data=run();print(json.dumps({"passed":len(data),"criteria":len({x['criterion'] for x in data})}))
