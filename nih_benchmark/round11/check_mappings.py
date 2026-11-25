"""Probe every active R10 gap through note intake, FHIR, and the released rule evaluator."""
import csv
from copy import deepcopy
from collections import Counter
import json
from catalog import HERE,R9,verify
from match import screen,read_json
from convert import build_case,LOCAL
from native import NativeChart
from clinical_fields import FIELDS,SKIN,MARITAL,STUDY_SECTIONS,MEASURE_SENTENCES,NARRATIVE
from rules_engine import evaluate

def write_table(path,records):
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(records[0]))
        w.writeheader();w.writerows(records)

def main():
    pack=verify(read_json(HERE/'compiled.json'))
    with (HERE.parent/'round10/results/engineering_mappings.csv').open() as f:prior=list(csv.DictReader(f))
    traces=read_json(HERE/'results/traces.json');assignments={str(a['annotation_id']):a for a in read_json(R9/'assignments.json')}
    notes=read_json(R9/'notes.json');table=[];passed=Counter()
    review=dict(line.split('|',1) for line in (HERE/'chart_review.psv').read_text().splitlines())
    def resources(line):
        bundle,_=build_case('probe','0. Patient test record.\n1. '+line,[],{},{},'2026-01-01T00:00:00Z')
        return [e['resource'] for e in bundle['entry']]
    for gap in prior:
        key=gap['fact'];cid=gap['contract'];k=gap['annotation_ids'];a=assignments[k]
        spec=pack['contracts'][cid]['spec'];fields=[f for f in FIELDS if key in f.facts]
        assert fields and pack['rules'][k]['bindings'][key]==cid
        for f in fields:
            if f.kind=='quantity':
                vals=[('2',2),('3',3)]
                if f.printed_unit:vals=[(v+' '+f.printed_unit,w) for v,w in vals]
            elif f==SKIN:vals=[(key.split('_')[-1],True),('VI',False)]
            elif f==MARITAL:vals=[('divorced',True),('married',False)]
            else:vals=[('yes',True),('no',False)]
            study=a['study']
            prefix=('Study '+study+' | ' if f.section in STUDY_SECTIONS else '')+f.context+': '
            for display,want in vals:
                rs=resources(prefix+display+'.')
                chart=NativeChart(rs,'Patient/probe',pack['contracts'],study)
                v,issue,refs,_=chart.read(spec)
                assert issue is None and v==want and chart.refs[refs[0]]==[1],(k,key,issue)
                node={'fact':key} if f.kind!='quantity' else {'fact':key,'op':'eq','value':2}
                assertion=evaluate({'facts':{key:spec},'expression':node},chart)
                expected=(want==2) if f.kind=='quantity' else want
                assert assertion['state']==('MET' if expected else 'NOT_MET')
                full=screen(rs,'Patient/probe',pack,study,k)['criteria'][k]
                # Conditional applicability can prevent evaluation of the leaf in an otherwise empty chart.
                if key in full['facts']:assert full['facts'][key]['value']==want
                passed['value checks']+=1
                if f.section in STUDY_SECTIONS:
                    assert NativeChart(rs,'Patient/probe',pack['contracts'],'NCT00000000').read(spec)[1]=='MISSING_DATA'
                    passed['wrong study checks']+=1
            for bad in [prefix+'unknown.', 'Family history: '+prefix+vals[0][0]+'.',prefix+vals[0][0]+' if symptoms worsen.']:
                assert NativeChart(resources(bad),'Patient/probe',pack['contracts'],study).read(spec)[1]=='MISSING_DATA'
                passed['uncertainty or scope checks']+=1
            if f.standard:
                rs=resources(prefix+vals[0][0]+'.')
                o=next(o for o in rs if o['resourceType']=='Observation')
                o['code']['coding']=[c for c in o['code']['coding'] if c['system']!=LOCAL]
                assert NativeChart(rs,'Patient/probe',pack['contracts'],study).read(spec)[0]==2
                o['valueQuantity']['code']='mg'
                assert NativeChart(rs,'Patient/probe',pack['contracts'],study).read(spec)[1]=='MISSING_DATA'
                passed['standard-only and unit checks']+=2
        t=traces[k]['criteria'][k];observed=t['facts'].get(key,{})
        table.append(dict(annotation_id=k,study=a['study'],patient=a['patient'],criterion=pack['rules'][k]['source']['criterion_text'],
                          chart_review=review[k],former_mapping_gap=key,selector_resource='Observation',source_fields=' | '.join(f.context for f in fields),
                          accepted_source_formats='Explicit structured report field'+(' or supported narrative sentence' if (key in {n[1] for n in NARRATIVE} or key in {n[0] for n in MEASURE_SENTENCES} or any(f in (SKIN,MARITAL) or f.section in {'Current chest CT final report','Current head CT final report'} for f in fields)) else ''),
                          actual_fact_state=observed.get('state','branch not reached'),criterion_state=t['state'],
                          partial_evidence=' | '.join(t.get('partial_evidence',[])),original_note=notes[a['patient']]))
    assert len({r['former_mapping_gap'] for r in table})==84 and len({r['annotation_id'] for r in table})==58
    # These real near misses should still abstain on the exact queried facts.
    for k,key in [('435','chest_ct_showed_ild'),('460','ct_intracranial_hemorrhage'),('212','refused_written_consent'),('332','gestation_at_birth_weeks')]:
        assert traces[k]['criteria'][k]['facts'][key]['state']=='MISSING_DATA'
        passed['original-chart near misses']+=1
    # Independently phrased sources exercise the complete clinical rule, including exclusion polarity.
    for k,line,want in [
        ('108','The patient is hemodynamically unstable.','NOT_MET'),
        ('108','The patient is not hemodynamically unstable.','MET'),
        ('108','The patient may be hemodynamically unstable.','MISSING_DATA'),
        ('187','Arterial blood gas / PaCO2: 32 mmHg.','MET'),
        ('187','Arterial blood gas showed a PaCO2 of 32 mmHg.','MET'),
        ('187','Venous blood gas showed a PaCO2 of 32 mmHg.','MISSING_DATA'),
        ('435','The current chest CT shows pulmonary thromboembolism.','NOT_MET'),
        ('435','The current chest X-ray shows pulmonary thromboembolism.','MISSING_DATA'),
        ('332','The patient was born at 35 weeks of gestation.','NOT_MET'),
        ('332','The patient was born at 36 weeks of gestation.','MET'),
        ('332','The patient is currently at 35 weeks of gestation.','MISSING_DATA'),
        ('187','Venous blood gas / PaCO2: 32 mmHg.','MISSING_DATA')]:
        assert screen(resources(line),'Patient/probe',pack,assignments[k]['study'],k)['criteria'][k]['state']==want
        passed['independent full-rule checks']+=1
    write_table(HERE/'results/resolved_mappings.csv',table)
    result={'formerly_blocked_contracts':len(table),'formerly_blocked_pairs':len(set(r['annotation_id'] for r in table)),'checks':dict(passed)}
    (HERE/'results/mapping_tests.json').write_text(json.dumps(result,indent=2)+'\n')
    print(result)
if __name__=='__main__':main()
