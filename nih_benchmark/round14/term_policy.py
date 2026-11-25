"""Optional research prescreen for adult exam terminology. Exact screening stays separate."""
import argparse
import base64
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "round12"))
from intake import plain_chart
from screen import R11, screen, verify, read_json
from catalog import fact
from native import NativeChart
from eligibility_engine import evaluate

PROFILE = "adult-exam-terms-r1"
REFERENCE = "https://www.ncbi.nlm.nih.gov/books/NBK591819/table/ch8oxygenation.T.symptoms_and_signs_of_r/"
BOUNDS = {"heart_rate": ("tachycardia", "tachycardic", 100), "respiratory_rate": ("tachypnea", "tachypneic", 20)}
AGE = fact("age_years", "number", "a")

def estimate(rule, strict, chart, note):
    """Only prove positive lower-bound predicates in an unresolved inclusion AND/OR tree."""
    if strict['state'] != 'MISSING_DATA' or 'applies' in rule:
        return []
    def visit(node):
        outcome = evaluate(dict(facts=rule['facts'], expression=node), chart)
        if outcome['state']=='MET':
            return [dict(method='direct', resources=outcome['evidence'])]
        if outcome['state']!='MISSING_DATA':
            return []
        if 'all' in node:
            branches = [visit(child) for child in node['all']]
            return [p for branch in branches for p in branch] if all(branches) else []
        if 'any' in node:
            return next((p for child in node['any'] if (p:=visit(child))), [])
        label = node.get('fact')
        if label not in BOUNDS or node.get('op') not in ('gt','ge'):
            return []
        detail = strict['facts'].get(label, {})
        spec = rule['facts'][label]
        # An available, contradictory or ambiguously coded measured rate always takes priority.
        if detail.get('state')!='MISSING_DATA' or detail.get('evidence') or spec!=fact(label,'number','/min'):
            return []
        sign, adjective, bound = BOUNDS[label]
        if node['value']>bound:
            return []
        age, issue, age_refs, _ = chart.read(AGE)
        if issue or age < 18:
            return []
        if any(chart.index.get(('Observation', system, code)) for system, code in [
                ('http://loinc.org', '8867-4' if label=='heart_rate' else '9279-1'),
                ('urn:pocketmd:trialgpt:clinical:v1', label)]):
            return []
        quantity_words = r'(?:heart rate|pulse|hr)' if label == 'heart_rate' else r'(?:respiratory rate|respirations|rr)'
        if re.search(r'\b'+quantity_words+r'\b[^.;\n]{0,32}\d',note,re.I):
            return []
        signs = chart.qualitative_context(label)
        lines = note.splitlines()
        # One attributable present-exam statement. Multiple mentions may indicate
        # a new timepoint, a correction, or another person's finding.
        mentioned = [i for i,line in enumerate(lines) if re.search(r'\b(?:'+sign+'|'+adjective+r')\b',line,re.I)]
        if len(signs)!=1 or signs[0]['source_lines']!=mentioned or len(mentioned)!=1:
            return []
        source_line=re.sub(r'^\s*\d+\.\s*','',lines[mentioned[0]])
        if not re.match(r'^On (?:physical )?examination,? (?:he|she|the patient) is ',source_line,re.I):
            return []
        return [dict(method='term_implies_lower_bound', fact=label, comparator=node['op'],
                     target=node['value'], sign=sign, assumed_open_lower_bound=bound,
                     age_years=age, resources=age_refs+[signs[0]['resource']], reference=REFERENCE)]
    proof=visit(rule['expression'])
    return proof if any(p['method']=='term_implies_lower_bound' for p in proof) else []

def prescreen(resources,subject,pack,study,criterion,policy=PROFILE):
    if policy!=PROFILE:raise ValueError('Unknown research policy')
    trace=screen(resources,subject,pack,study,criterion)
    case=trace['criteria'][criterion]
    entry=pack['rules'][criterion]
    proof=[]
    if case['state']=='MISSING_DATA' and entry['source']['criterion_type']=='inclusion':
        chart=NativeChart(resources,subject,pack['contracts'],study)
        doc=next(x for x in resources if x.get('resourceType')=='DocumentReference' and 'DocumentReference/'+x['id']==chart.source)
        raw=base64.b64decode(doc['content'][0]['attachment']['data'],validate=True).decode()
        proof=estimate(entry['rule'],case,chart,raw)
    trace['research_prescreen']=dict(policy=policy,state='SUPPORTED_PENDING_MEASUREMENT' if proof else 'NO_ADDITIONAL_RESULT',
            assumptions='Use the adult textbook definitions for a contemporaneous patient examination; resting state and site-specific convention are unverified.',proof=proof)
    return trace

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--subject',required=True);parser.add_argument('--study',required=True);parser.add_argument('--criterion',required=True)
    parser.add_argument('--catalog',type=Path,default=R11/'compiled.json')
    args=parser.parse_args(); pack=verify(read_json(args.catalog))
    result=prescreen([x['resource'] for x in read_json(args.bundle)['entry']],args.subject,pack,args.study,args.criterion)
    print(json.dumps(result,indent=2))
