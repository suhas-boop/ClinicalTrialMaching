"""Protocol activation and document scope at the normal FHIR screening entry point."""
import json
import subprocess
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

import test_clarify
from clarify import BENCH, CASE, PATIENT, STUDY, plain_chart, read_json, fingerprint
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review706.release import screen_reviewed


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        # The existing fixture generates a temporary synthetic authority and protocol.
        fixture = test_clarify.ProtocolTests()
        fixture.setUp()
        self.fx = fixture
        self.pack = read_json(BENCH/'round11/compiled.json')

    def run_screen(self, text=None, **changes):
        if text is None:
            bundle = self.fx.bundle
            subject = 'Patient/'+PATIENT
        else:
            bundle = plain_chart('another-patient',text,'2026-01-01T00:00:00Z')[0]
            subject = 'Patient/another-patient'
        resources = [e['resource'] for e in bundle['entry']]
        args = dict(envelope=self.fx.sign(),trust=self.fx.trust,
                    protocol_bytes=self.fx.proto,as_of=self.fx.asof)
        args.update(changes)
        return screen_reviewed(resources,subject,self.pack,STUDY,CASE,**args)

    def test_versioned_catalog_and_exact_source(self):
        base_hash=fingerprint(self.pack)
        bare=self.run_screen(envelope=None)
        approved=self.run_screen()
        row=approved['criteria'][CASE]
        self.assertEqual(bare['criteria'][CASE]['state'],'AUTHORING_HOLD')
        self.assertEqual(row['state'],'MET')
        self.assertEqual(len(row['source_spans']),4)
        text=read_json(BENCH/'round9/notes.json')[PATIENT]
        self.assertEqual(row['source_sentences'],[0])
        self.assertEqual(set(row['evidence']),set(row['source_spans']))
        for ref, span in row['source_spans'].items():
            self.assertEqual(text[span['start']:span['end']],span['quote'])
            self.assertIn(approved['source_sha256'],ref)
        self.assertTrue(all(f['contract'] for f in row['facts'].values()))
        self.assertNotEqual(bare['catalog_sha256'],approved['catalog_sha256'])
        self.assertEqual(bare['catalog_sha256'],approved['base_catalog_sha256'])
        self.assertEqual(approved['catalog_sha256'],self.run_screen()['catalog_sha256'])
        self.assertEqual(base_hash,fingerprint(self.pack))
        self.assertEqual(self.fx.run_case()['state'],row['state'])

    def test_different_subject_and_sections(self):
        prefix='The patient is a woman.\n'
        probe='She reports dyspareunia.'
        self.assertEqual(self.run_screen(prefix+probe)['criteria'][CASE]['state'],'MET')
        cases=[
            'Family history:\n'+probe, 'Family history\n'+probe,
            'Family history: Mother has endometriosis.\n'+probe,
            'Family history: Mother has endometriosis.\nShe reports heavy menstrual periods.',
            'Past medical history:\n'+probe, 'PMH\n'+probe,
            'Her maternal aunt visits.\n'+probe, 'Last year she described a different problem.\n'+probe,
            "Review of sister's symptoms:\n"+probe,
            "The patient's wife is a woman.\n"+probe,
            'The patient is a man.\nThe patient reports dyspareunia.',
            'The patient is male.\nThe patient reports dyspareunia.',
            'Sex: male\nThe patient reports dyspareunia.',
            probe+'\nCorrection: current dyspareunia is uncertain.',
        ]
        for suffix in cases:
            with self.subTest(suffix=suffix):
                self.assertEqual(self.run_screen(prefix+suffix)['criteria'][CASE]['state'],'MISSING_DATA')
        restored=prefix+'Past medical history:\n'+probe+'\nCurrent symptoms:\nThe patient reports menorrhagia.'
        self.assertEqual(self.run_screen(restored)['criteria'][CASE]['state'],'MET')

    def test_decision_rechecked_at_execution(self):
        self.run_screen()
        self.fx.trust['revoked'].append('simulation')
        with self.assertRaisesRegex(ValueError,'revoked'):
            self.run_screen()
        self.fx.trust['revoked'].clear()
        self.fx.payload['interpretation']['operator']='ALL'
        self.assertEqual(self.run_screen()['criteria'][CASE]['state'],'MISSING_DATA')
        self.fx.payload['interpretation']['operator']='ANY'
        self.fx.payload['interpretation']['requirement']='also_require_separate_diagnosis'
        self.assertEqual(self.run_screen()['criteria'][CASE]['state'],'MISSING_DATA')
        self.assertEqual(self.run_screen('The patient is a woman.\nShe reports dyspareunia.\nThe patient has a confirmed diagnosis of pelvic congestion.')['criteria'][CASE]['state'],'MET')
        self.fx.payload['governing_version']='unreviewed'
        with self.assertRaisesRegex(ValueError,'version'):
            self.run_screen()

    def test_normal_cli_and_wrong_source(self):
        with TemporaryDirectory() as path:
            root=Path(path)
            for key,value in [('bundle',self.fx.bundle),('answer',self.fx.sign()),('trust',self.fx.trust)]:
                (root/key).write_text(json.dumps(value))
            (root/'protocol').write_bytes(self.fx.proto)
            base=[sys.executable,'-B',str(BENCH.parent/'pocketmd.py'),'fhir-screen','--study',STUDY,
                  '--subject','Patient/'+PATIENT,'--criterion',CASE,'--bundle',str(root/'bundle')]
            reviewed=base+['--review-answer',str(root/'answer'),'--review-trust',str(root/'trust'),
                           '--governing-protocol',str(root/'protocol'),'--as-of',self.fx.asof.isoformat()]
            def call(args): return subprocess.run(args,text=True,capture_output=True)
            self.assertEqual(json.loads(call(base).stdout)['criteria'][CASE]['state'],'AUTHORING_HOLD')
            self.assertEqual(json.loads(call(reviewed).stdout)['criteria'][CASE]['state'],'MET')
            self.fx.trust['revoked']=['simulation']
            (root/'trust').write_text(json.dumps(self.fx.trust))
            rejected=call(reviewed)
            self.assertNotEqual(rejected.returncode,0)
            self.assertIn('revoked',rejected.stderr)
            self.assertFalse(rejected.stdout)
            changed=deepcopy(self.fx.bundle)
            document=next(e['resource'] for e in changed['entry'] if e['resource']['resourceType']=='DocumentReference')
            document['subject']['reference']='Patient/different'
            (root/'bundle').write_text(json.dumps(changed))
            self.assertNotEqual(call(base).returncode,0)

if __name__=='__main__': unittest.main()
