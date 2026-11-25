"""Run existing PocketMD rules on exported FHIR only. TrialGPT labels are never used for binding."""
from collections import Counter,defaultdict
from contextlib import closing
import csv,json,hashlib,base64,argparse
from pathlib import Path
from convert import HERE,R8,LOINC,LOCAL,UNIT,MEASURES,SCOPE,LINE,load,dump,rid,admits
from chart import open_chart,search
from run import load_cases,fingerprint
from evidence_review import screen_snapshot
from bindings import ROLE_MISSING
from rules_engine import typed

class VignetteChart:
    def __init__(self,resources,subject):
        self.subject=subject
        self.records={rid(r):r for r in resources}
        self.source='DocumentReference/'+subject.split('/')[1]+'-note'
        d=self.records[self.source]
        if d['status']!='current' or d['subject']['reference']!=subject:raise ValueError('Wrong source document')
        raw=base64.b64decode(d['content'][0]['attachment']['data'],validate=True)
        self.hash=hashlib.sha256(raw).hexdigest()
        if not any(i.get('system')=='urn:pocketmd:sha256' and i['value']==self.hash for i in d['identifier']):raise ValueError('Invalid source digest')
        lines=raw.decode().splitlines()
        self.refs={}
        self.facts=defaultdict(list)
        for p in resources:
            if p['resourceType']!='Provenance':continue
            if p['agent']!=[{'who':{'reference':'Device/pocketmd-r9'}}] or 'Device/pocketmd-r9' not in self.records:continue
            target=p['target'][0]['reference'];e=p['entity'][0]
            if e['role']!='source' or e['what']['reference']!=self.source:continue
            ids=[x['valueInteger'] for x in e['extension'] if x['url']==LINE]
            if not ids or any(i<0 or i>=len(lines) for i in ids):raise ValueError('Broken source sentence reference')
            self.refs[target]=ids
        for target,indices in self.refs.items():
            r=self.records[target]
            if r.get('subject',{}).get('reference')!=subject:continue
            if r.get('modifierExtension') or r.get('implicitRules'):continue
            scope=next((x['valueString'] for x in r.get('extension',[]) if x['url']==SCOPE),None)
            codes={(c['system'],c['code']) for c in r.get('code',{}).get('coding',[])}
            if r['resourceType']=='Condition':
                if (LOCAL,'myocardial-infarction') in codes and (scope or '').split(';')[0]=='history':
                    self.facts['history_of_mi'].append((True,target,None))
                continue
            if r['resourceType']!='Observation' or r.get('status')!='final' or r.get('derivedFrom')!=[{'reference':self.source}]:continue
            for system,k in codes:
                if system!=LOCAL:continue
                if 'valueBoolean' in r and scope=='note abstraction':
                    self.facts[k].append((r['valueBoolean'],target,None))
                if k in {'age-at-presentation','heart_rate','respiratory_rate','gcs','serum_creatinine_mg_dl'}:
                    expected='age at vignette presentation' if k=='age-at-presentation' else 'presentation'
                    if scope!=expected or (LOINC,MEASURES[k][0]) not in codes:continue
                    q=r.get('valueQuantity',{})
                    if 'comparator' in q or q.get('system')!=UNIT:continue
                    self.facts['age_years' if k=='age-at-presentation' else k].append((q['value'],target,q['code']))
    def read(self,spec):
        key=spec['label']
        if not admits(key,spec):return None,ROLE_MISSING[spec['role']],[],'Obtain verified '+spec['scope']+'.'
        matches=[(v,ref) for v,ref,unit in self.facts.get(key,[]) if typed(v,spec) and unit==spec.get('unit')]
        if not matches:return None,'MISSING_DATA',[],'The converted chart lacks a verified value for '+spec['scope']+'.'
        refs=sorted({r for _,r in matches})
        if len({v for v,_ in matches})!=1:return None,'MISSING_DATA',refs,'Reconcile conflicting measurements.'
        return matches[0][0],None,refs,'Source-linked '+spec['scope']+'.'

def replay(export):
    packs=load(R8/'results/rules.json')
    assignments={str(r['annotation_id']):r for r in load(HERE/'assignments.json')}
    if set(assignments)!=set(packs):raise ValueError('Benchmark population mismatch')
    subj={r['case']:r['subject'] for r in load(export/'cases.json')};rows=[];traces={}
    with closing(open_chart(export/'chart.sqlite')) as db:
        for cid,entry in sorted(packs.items(),key=lambda x:int(x[0])):
            row=assignments[cid];subject=subj[row['patient']];snap=VignetteChart(search(db,subject),subject)
            ctx={'patient':subject,'episode':'benchmark presentation','encounter':'benchmark vignette','as_of':snap.hash,
                 'source_scope':'multiple_subjects' if subject.startswith('Group/') else 'individual','source_sha256':snap.hash}
            # This is a source snapshot; no absolute trial visit time is inferred.
            study=entry['source']['trial_id']
            ver=fingerprint({k:v for k,v in packs.items() if v['source']['trial_id']==study})
            verdict=screen_snapshot({cid:entry['rule']},snap,ctx,study,ver)
            v=verdict['criteria'][cid]
            ids=sorted({i for ref in v['evidence'] for i in snap.refs[ref]})
            rows.append(dict(annotation_id=cid,subject=subject,study=study,fhir_result=v['state'],
                             source_resource_ids=' | '.join(v['evidence']),source_sentences=ids))
            traces[cid]=verdict
    # Scoring and historical comparison occur only after all FHIR predictions exist.
    prediction_sha256=fingerprint(rows)
    prior={str(r['annotation_id']):r for r in csv.DictReader((R8/'results/scored_cases.csv').open())}
    for row in rows:
        comparison=prior[row['annotation_id']]
        row.update(previous=comparison['patient_result'],expert_state=comparison['expert_state'])
    with (export/'matching.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
    dump(export/'matching_traces.json',traces)
    binary=[r for r in rows if r['fhir_result'] in ('MET','NOT_MET')]
    res={'prediction_sha256':prediction_sha256,'cases':len(rows),'changed':sum(r['previous']!=r['fhir_result'] for r in rows),'fhir_results':dict(Counter(r['fhir_result'] for r in rows)),
         'binary_agreement':sum(r['expert_state']==r['fhir_result'] for r in binary),'definite_results':len(binary)}
    dump(export/'matching_summary.json',res);return res
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('export',type=Path);print(replay(p.parse_args().export))
