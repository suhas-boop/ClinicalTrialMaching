"""Use an ephemeral test key and isolated trust to display the possible answers to #706."""
import json
from test_clarify import ProtocolTests

def run():
    test=ProtocolTests();test.setUp()
    results=[]
    for operator in ('ANY','ALL'):
        for requirement in ('symptoms_suffice','also_require_separate_diagnosis'):
            test.payload['interpretation'].update(operator=operator,requirement=requirement)
            t=test.run_case()
            results.append(dict(operator=operator,requirement=requirement,state=t['state'],
                         source_sha256=t['source_sha256'],facts=t['facts'],source_spans=t['source_spans']))
    return dict(experiment='Simulated protocol-authority responses using an ephemeral key. The patient document is original.',
                original_state=test.run_case(envelope=None)['state'],actual_approved_responses=0,
                additional_definite_original_score=0,maximum_additional_decisions_if_answered=1,
                simulated_outcomes=results)
if __name__=='__main__': print(json.dumps(run(),indent=2))
