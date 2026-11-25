"""Replay both studies on the packaged synthetic inputs, without network access."""
import json
from pathlib import Path
import subprocess
import sys

import test_entry_adapter
import test_organ_adapter
import test_heart_adapter
import test_therapy_adapter
from normalized import ROOT, make_packet
from verify_rules import run as verify_cases
from screen_study import evaluate_normalized, screen

def read(p):
    return json.loads(p.read_text())

def verify():
    index=read(ROOT/"study-index.json")
    rules=read(ROOT/"sotio_rules.json")
    reg=read(ROOT/"legacy"/"legacy_replays.json")
    cases=read(ROOT/"sotio_cases.json")
    base=verify_cases()
    for c in cases:
        packet=make_packet(rules,{c["criterion"]:c["values"]})
        state=evaluate_normalized(rules,packet["bundle"],packet["context"])[c["criterion"]]["state"]
        if state!=c["expected"]:raise AssertionError((c["criterion"],c["name"],state))
    native={k:len(fn(rules)) for k,fn in [("prescreen_disease",test_entry_adapter.run_checks),
            ("organ",test_organ_adapter.run_checks),("heart_rate",test_heart_adapter.run_checks),
            ("drug_exposure",test_therapy_adapter.checks)]}
    confirmed=0
    examples=0
    scopes={}
    for study in index['studies']:
        sid=study['study']
        mapping={c['id']:c for c in study['criteria']}
        assert len(mapping)==(42 if sid=='106S01' else 3)
        scopes[sid]=[c['id'] for c in study['criteria'] if c['holds']]
        for s in study['scenarios']:
            packet=read(ROOT/'examples'/(s['id']+'.json'))
            result=screen(packet)
            assert set(result['criteria'])==set(mapping)
            examples+=1
            if sid=='NCT05653388':
                expect=reg[sid][s['id'].removeprefix('michigan-')]
                for cid in mapping:
                    assert result['criteria'][cid]==expect['criteria'][cid]
                    confirmed+=1
    legacy=json.loads(subprocess.check_output([sys.executable,'-B',str(ROOT/'legacy'/'verify_bridge.py')]))
    assert legacy['michigan_frozen_expectations']==confirmed==114
    return dict(normalized_criterion_cases=len(cases),normalized_including_integrity=len(base),native_checks=native,
                checked_whole_study_packets=examples,michigan_frozen_decisions=confirmed,protocol_clarification_branches=scopes)
if __name__=='__main__':
    print(json.dumps(verify(),indent=2))
