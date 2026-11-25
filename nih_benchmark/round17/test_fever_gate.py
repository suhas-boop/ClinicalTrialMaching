"""Verify episode selection, strict boundary, provenance and the study-level denominator."""
import base64
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

import fever_gate as fever
from intake import plain_chart


class FeverGateTests(unittest.TestCase):
    def resources(self, note, patient='other-patient'):
        bundle, _ = plain_chart(patient, note, '2026-01-01T00:00:00Z')
        return [x['resource'] for x in bundle['entry']]

    def receipt(self, note, patient='other-patient'):
        return fever.screen_fever(self.resources(note,patient), 'Patient/'+patient, fever.STUDY)

    def test_different_subject_and_strict_boundary_use_shared_matcher(self):
        for days,expected in [(2,'NOT_MET'),(7,'NOT_MET'),(8,'MET')]:
            note=f'The patient presents with fever for {days} days.'
            result=self.receipt(note)
            self.assertEqual((result['state'],result['value_days'],result['subject']), (expected,days,'Patient/other-patient'))
            self.assertEqual(result['source_sha256'],sha256(note.encode()).hexdigest())
            self.assertEqual(result['catalog_sha256'],fever.catalog(fever.protocol())['sha256'])
            self.assertEqual(result['source_spans'][result['evidence'][0]]['quote'],note)
        self.assertEqual(self.receipt('The patient reports 2 weeks of fever and cough.')['value_days'],14)
        self.assertEqual(self.receipt('The patient reports fever and cough, all for 8 days.')['state'],'MET')

    def test_scope_and_duration_attachment(self):
        for note in (
            'The patient had fever for 2 days last week.',
            'His brother presents with fever for 2 days.',
            'The patient presents with cough for 2 days and fever.',
            'The patient presents with fever and cough for 2 days.',
            'The patient has had fever on and off for 2 days.',
            'The patient reports fever for approximately 8 days.',
            'The patient reports fever for two or three weeks.',
            'The patient presents with fever of unknown duration.',
            'The patient reports fever for 2 days.\nHe has actually had fever for 15 days.',
            'The patient reports fever for 2 days.\nThe illness began last month.',
            'The patient reports fever for 2 days.\nThere was a symptom-free interval.',
            'The patient reports fever for 2 days.\nNow afebrile.',
            'The patient reports fever for 2 days.\nCorrection: prior symptoms were continuous.',
            'Past medical history:\nThe patient presents with fever for 2 days.',
            'A boy presents with fever, chills and cough for 2 days.\nParents report that prior to the onset of fever and chills, he had loose stools.',
            'A boy presents with fever, chills and cough for 2 days.\nParents report that prior to the onset of fever and cough, she had loose stools.',
            'A boy presents with fever, chills and cough for 2 days.\nFamily history:\nParents report that prior to the onset of fever and cough, he had loose stools.',
        ):
            with self.subTest(note=note):
                result=self.receipt(note)
                self.assertEqual((result['state'],result['value_days'],result['evidence']),('MISSING_DATA',None,[]))

    def test_corroboration_and_offsets(self):
        note=('0. An 11-year-old girl presents to the ED with fever up to 39 °C, chills and cough for 8 days.\n'
              '1. Parents report that prior to the onset of fever and cough, she had loose stools.')
        receipt=self.receipt(note)
        self.assertEqual(receipt['state'],'MET')
        self.assertEqual(sorted(s['line'] for s in receipt['source_spans'].values()),[0,1])
        for source in receipt['source_spans'].values():
            self.assertEqual(note[source['start']:source['end']],source['quote'])
        self.assertEqual(self.receipt(note.splitlines()[0])['state'],'MISSING_DATA')

    def test_subject_digest_and_study_guards(self):
        note='The patient reports fever for 8 days.'
        rs=self.resources(note)
        self.assertIsNone(fever.screen_fever(rs,'Patient/other-patient','NCT00000000'))
        with self.assertRaises(ValueError):
            fever.screen_fever(rs,'Patient/other-patient',fever.STUDY,expected_source_sha256='a'*64)
        with self.assertRaises(ValueError):
            fever.screen_fever(rs,'Patient/other',fever.STUDY)
        doc=next(r for r in rs if r['resourceType']=='DocumentReference')
        foreign=deepcopy(doc)
        foreign['id']='another-note'
        foreign['subject']={'reference':'Patient/someone-else'}
        with self.assertRaises(ValueError):
            fever.screen_fever(rs+[foreign],'Patient/other-patient',fever.STUDY)
        doc['content'][0]['attachment']['data']=base64.b64encode(b'The patient reports fever for 5 days.').decode()
        with self.assertRaises(ValueError):
            fever.screen_fever(rs,'Patient/other-patient',fever.STUDY)

    def test_source_pin_and_unchanged_frozen_assignments(self):
        with tempfile.TemporaryDirectory() as temp:
            edited=Path(temp)/'study.json'
            edited.write_bytes(fever.SOURCE.read_bytes().replace(b'more than one week',b'at least one week'))
            with self.assertRaises(ValueError):
                fever.protocol(edited)
        result=fever.replay()
        self.assertEqual((result['assignments'],result['patient_study_pairs'],len(result['gates'])),(134,68,1))
        self.assertFalse(result['frozen_criterion_scores_modified'])
        gate=result['gates'][0]
        self.assertEqual((gate['state'],gate['value_days'],gate['linked_frozen_criteria']),('NOT_MET',2,[34,36]))
        source=gate['protocol']
        raw=json.loads(fever.SOURCE.read_bytes())['protocolSection']['eligibilityModule']['eligibilityCriteria']
        self.assertEqual(raw[source['start']:source['end']],source['criterion_text'])


if __name__=='__main__':
    unittest.main()
