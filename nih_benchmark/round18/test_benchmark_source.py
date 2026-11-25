"""A dataset author adds one final sentence. Preserve its origin through fresh FHIR conversion."""
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BENCH/'round16'))
from literal_scope import R11, frozen_assignments, screen, verify
from benchmark_source import APPENDED,PRODUCER,ROLE
from intake import benchmark_chart, plain_chart

def origin(resources):
    doc = next(r for r in resources if r['resourceType']=='DocumentReference')
    marks = [v for v in doc.get('extension',[]) if v['url']==ROLE]
    return doc, marks

def resources(bundle):
    return [e['resource'] for e in bundle['entry']]

def has_consent_finding(items):
    return any('consent' in c.get('code','') for r in items if r['resourceType']=='Observation'
               for c in r['code']['coding'])

def text(path):
    return json.loads(path.read_text())

class SourceRoleTests(unittest.TestCase):
    def setUp(self):
        self.pid='sigir-201413'
        self.note=text(BENCH/'round9/notes.json')[self.pid]
        self.stamp='2026-01-01T00:00:00Z'

    def test_identical_text_has_different_verified_origins(self):
        benchmark, protected_spans = benchmark_chart(self.pid,self.note,self.stamp)
        genuine, original_spans = plain_chart(self.pid,self.note,self.stamp)
        b, g = resources(benchmark), resources(genuine)
        db, mb = origin(b)
        dg, mg = origin(g)
        self.assertEqual(db['content'],dg['content'])
        self.assertEqual(db['identifier'],dg['identifier'])
        self.assertEqual(len(mb),1)
        self.assertEqual(mg,[])
        self.assertFalse(has_consent_finding(b))
        self.assertTrue(has_consent_finding(g))
        values={e['url']:next(v for k,v in e.items() if k.startswith('value')) for e in mb[0]['extension']}
        self.assertEqual(values['role'],'benchmark-assumption')
        self.assertEqual(values['producer'],PRODUCER)
        self.assertEqual(self.note[values['characterStart']:values['characterEnd']],APPENDED)
        self.assertEqual(protected_spans,[s for s in original_spans if values['sourceSentence'] not in s['sentences']])
        self.assertTrue(has_consent_finding(resources(plain_chart('new-document',self.note,self.stamp)[0])))

    def test_identity_and_content_are_checked(self):
        for pid, source in [('another',self.note),(self.pid,self.note.replace('30-year-old','31-year-old')),
                           (self.pid,self.note.replace('consent','approval'))]:
            with self.subTest(pid=pid,source=source[:60]),self.assertRaises(ValueError):
                benchmark_chart(pid,source,self.stamp)

    def test_all_assignments_have_annotated_source_and_no_assertion_from_last_line(self):
        count=0
        for r,subject,items,approved in frozen_assignments():
            count+=1
            doc,marks=origin(items)
            self.assertEqual(len(marks),1)
            body=base64.b64decode(doc['content'][0]['attachment']['data']).decode()
            n=len(body.splitlines())-1
            for p in (x for x in items if x['resourceType']=='Provenance'):
                for e in p['entity']:
                    self.assertFalse(any(v.get('url')=='urn:pocketmd:trialgpt:source-sentence' and
                                         v.get('valueInteger')==n for v in e.get('extension',[])))
            self.assertIn(approved[subject], [x['value'] for x in doc['identifier']])
        self.assertEqual(count,134)

    def test_single_note_partial_and_decisive_source_lines(self):
        pack = verify(text(R11 / 'compiled.json'))
        expected = {
            '26': ('MISSING_DATA', [0], [0]),  # the evaluated conditional gate already has evidence
            '454': ('MISSING_DATA', [], [0]),  # age and sex from the same sentence
            '460': ('MISSING_DATA', [], [5]),  # GCS with no CT result
            '467': ('MISSING_DATA', [], None),
            '481': ('SOURCE_SCOPE_HOLD', [], None),
            '517': ('MET', [0], None),
        }
        checked = set()
        for assignment, subject, items, _ in frozen_assignments():
            key = str(assignment['annotation_id'])
            if key in expected:
                checked.add(key)
                with self.subTest(criterion=key):
                    state, source_lines, partial = expected[key]
                    row = screen(items, subject, pack, assignment['study'], key)['criteria'][key]
                    self.assertEqual(row['state'], state)
                    self.assertEqual(row['source_sentences'], source_lines)
                    self.assertEqual(bool(row['evidence']), bool(source_lines))
                    if partial is None:
                        self.assertNotIn('partial_source_sentences', row)
                    else:
                        self.assertEqual(row['partial_source_sentences'], partial)
                        self.assertTrue(row['partial_evidence'])
        self.assertEqual(checked, set(expected))

    def test_normal_cli_ordinary_frozen_and_bulk_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp=Path(directory)
            (tmp/'note').write_text(self.note)
            cli=[sys.executable,'-B',str(BENCH.parent/'pocketmd.py'),'fhir-convert']
            for extra,marked in [([],False),(['--frozen-trialgpt'],True)]:
                subprocess.run(cli+[str(tmp/'bundle'),'--note',str(tmp/'note'),'--patient',self.pid]+extra,
                               capture_output=True,check=True)
                items=resources(text(tmp/'bundle'))
                self.assertEqual(bool(origin(items)[1]),marked)
                self.assertEqual(has_consent_finding(items),not marked)
            subprocess.run(cli+[str(tmp/'batch'),'--recorded',self.stamp],capture_output=True,check=True)
            notes=text(BENCH/'round9/notes.json')
            for pid in notes:
                bundle=text(tmp/'batch/bundles'/(pid+'.json'))
                items=resources(bundle)
                self.assertTrue(origin(items)[1])
                suffix=len(notes[pid].splitlines())-1
                self.assertFalse(any(x.get('url')=='urn:pocketmd:trialgpt:source-sentence' and
                                     x.get('valueInteger')==suffix for p in items if p['resourceType']=='Provenance'
                                     for e in p['entity'] for x in e.get('extension',[])))

if __name__=='__main__':
    unittest.main()
