import copy
import unittest
from catalog import compile_pack, verify, HERE, R9, fact, contract
from match import read_json, screen
from convert import review_table,build_case
from native import NativeChart
from evidence_review import screen as normalized_screen
from run import fingerprint
from bindings import make_packet

class MappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack=verify(read_json(HERE/'compiled.json'))
        cls.assign={str(a['annotation_id']):a for a in read_json(R9/'assignments.json')}
        cls.notes=read_json(R9/'notes.json')
        cls.table=review_table()

    def resources(self,k,line=None,quantity=None):
        pid=self.assign[k]['patient']
        note=self.notes[pid]
        curated=list(self.table.get(pid,[]))
        if line:
            idx=len(note.splitlines())
            note=note.rstrip()+'\n'+str(idx)+'. '+line
            if quantity:curated.append((idx,'Observation','heart_rate',line,'presentation',quantity))
        bundle,_=build_case(pid,note,curated,read_json(R9/'rxnorm.json'),read_json(R9/'icd10cm.json'),'2026-01-01T00:00:00Z')
        return [e['resource'] for e in bundle['entry']]

    def run_case(self,k,rs):
        a=self.assign[k]
        return screen(rs,'Patient/'+a['patient'],self.pack,a['study'],k)

    def test_catalog_rebuild_and_frozen_rule_equivalence(self):
        self.assertEqual(compile_pack(),self.pack)
        previous=read_json(R9.parent/'round8/results/rules.json')
        current = self.pack['rules']
        self.assertEqual(set(current), set(previous))
        approved = read_json(HERE.parent/'round14/approved_revisions.json')
        differences = {}
        for key, entry in current.items():
            # Each amendment retains the original registered criterion and locator.
            self.assertEqual({k:entry['source'][k] for k in previous[key]['source']}, previous[key]['source'])
            if entry['source'] != previous[key]['source'] or entry['rule'] != previous[key]['rule']:
                differences[key] = dict(source_sha256=fingerprint(entry['source']), rule_sha256=fingerprint(entry['rule']))
        self.assertEqual(differences, approved)
        changed=copy.deepcopy(self.pack)
        changed['rules']['116']['bindings'].clear()
        with self.assertRaises(ValueError):verify(changed)

    def test_clinical_attribution_binds_both_paths_and_preserves_negation(self):
        k='116';entry=self.pack['rules'][k];key='cutaneous_ulcer_due_to_burns'
        study=entry['source']['trial_id']
        version=fingerprint({i:{n:v[n] for n in ('source','rule')} for i,v in self.pack['rules'].items() if v['source']['trial_id']==study})
        for line,value,want in [('The patient has a cutaneous ulcer due to burns.',True,'NOT_MET'),
                               ('The patient does not have a cutaneous ulcer due to burns.',False,'MET')]:
            with self.subTest(line=line):
                v=self.run_case(k,self.resources(k,line))['criteria'][k]
                self.assertEqual(v['state'],want);self.assertTrue(v['evidence'])
                self.assertEqual(v['facts'][key]['contract'],contract(entry['rule']['facts'][key]))
                rules={k:entry['rule']}
                packet=make_packet(rules,{k:{key:value}},study,version)
                self.assertEqual(normalized_screen(rules,packet,study,version)['criteria'][k]['state'],want)
        self.assertEqual(self.run_case(k,self.resources(k))['criteria'][k]['state'],'MISSING_DATA')

    def test_threshold_and_qualitative_evidence(self):
        for number,want in [(None,'MISSING_DATA'),(89,'NOT_MET'),(90,'MET')]:
            kw={} if number is None else dict(line=f'Heart rate {number} bpm.',quantity=[str(number),'/min'])
            self.assertEqual(self.run_case('186',self.resources('186',**kw))['criteria']['186']['state'],want)

    def test_unmapped_vs_mapped_absence(self):
        t=self.run_case('20',self.resources('20'))
        self.assertEqual(t['criteria']['20']['state'],'MISSING_DATA')
        self.assertEqual([q['route'] for q in t['requests']],['retrieve_record'])
        t=self.run_case('116',self.resources('116'))
        self.assertEqual([q['route'] for q in t['requests']],['retrieve_record'])

    def test_scope_patient_provenance_and_conflicts(self):
        k='116';key='cutaneous_ulcer_due_to_burns';rs=self.resources(k,'The patient has a cutaneous ulcer due to burns.')
        idx=next(i for i,r in enumerate(rs) if any(c['code']==key for c in r.get('code',{}).get('coding',[])))
        for change in ('subject','modifier','source','role','scope','missing-source','bad-type','conflict'):
            with self.subTest(change=change):
                case=copy.deepcopy(rs);obs=case[idx]
                if change=='subject':obs['subject']={'reference':'Patient/different'}
                if change=='modifier':obs['modifierExtension']=[{'url':'urn:test','valueBoolean':True}]
                if change=='source':obs['derivedFrom']=[]
                if change=='scope':obs['extension'][0]['valueString']='family history'
                if change=='bad-type':obs['valueBoolean']='true'
                target='Observation/'+obs['id']
                prov=next(r for r in case if r.get('target')==[{'reference':target}])
                if change=='role':prov['agent'][0]['who']['reference']='Device/other'
                if change=='missing-source':case.remove(prov)
                if change=='conflict':
                    dup=copy.deepcopy(obs);dup['id']+='-other';dup['valueBoolean']=False
                    p=copy.deepcopy(prov);p['id']+='-other';p['target'][0]['reference']=target+'-other';case.extend([dup,p])
                self.assertEqual(self.run_case(k,case)['criteria'][k]['state'],'MISSING_DATA')

    def test_changed_fact_semantics_fail_closed(self):
        a=self.assign['116']
        snap=NativeChart(self.resources('116','The patient has a cutaneous ulcer due to burns.'),'Patient/'+a['patient'],self.pack['contracts'])
        self.assertEqual(snap.read(fact('cutaneous_ulcer_due_to_burns',scope='remote historical burn'))[1],'BINDING_HOLD')

    def test_no_boolean_from_related_evidence(self):
        self.assertEqual(self.run_case('138',self.resources('138'))['criteria']['138']['state'],'MISSING_DATA')

if __name__=='__main__':unittest.main()
