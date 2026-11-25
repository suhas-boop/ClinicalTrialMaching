from copy import deepcopy
import unittest
from intake import plain_chart,LINE,END,START
from screen import R11,screen,read_json,verify
from native import NativeChart
from clinical_fields import BY_NAME

class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack=verify(read_json(R11/'compiled.json'))

    def resolve(self,note,k='435'):
        b,spans=plain_chart('demo',note,'2026-01-01T00:00:00Z')
        items=[e['resource'] for e in b['entry']]
        v=screen(items,'Patient/demo',self.pack,self.pack['rules'][k]['source']['trial_id'],k)['criteria'][k]
        return v,items,spans

    def test_rule_outcomes_and_source(self):
        positive,_,spans=self.resolve('Current chest CT:\nNo interstitial lung disease. Pulmonary embolism is suspected.\nCT chest today showed pulmonary embolism.')
        self.assertEqual(positive['state'],'NOT_MET');self.assertTrue(positive['evidence'])
        cites={x['resource']:x['excerpt'] for x in spans}
        self.assertIn('CT chest today showed pulmonary embolism.',[cites[e] for e in positive['evidence']])
        negative,_,_=self.resolve('Current chest CT:\nNo pulmonary embolism, interstitial lung disease, lung cancer or active pulmonary tuberculosis.')
        self.assertEqual(negative['state'],'MET')
        partial,_,_=self.resolve('Chest CT today showed no interstitial lung disease.')
        self.assertEqual(partial['state'],'MISSING_DATA');self.assertTrue(partial['partial_evidence'])

    def test_multiple_sentences_conflict_and_redelivery(self):
        note='Head CT today showed cerebral edema. Head CT today showed no cerebral edema.'
        b1,links=plain_chart('demo',note,'2026-01-01T00:00:00Z');b2,_=plain_chart('demo',note,'2026-01-01T00:00:00Z')
        self.assertEqual(b1,b2);self.assertEqual(len(links),2)
        s=NativeChart([e['resource'] for e in b1['entry']],'Patient/demo',self.pack['contracts'])
        spec=self.pack['rules']['460']['rule']['facts']['ct_cerebral_edema']
        self.assertEqual(s.read(spec)[1],'MISSING_DATA');self.assertEqual(len(s.read(spec)[2]),2)
        for x in links:self.assertEqual(note[x['start']:x['end']],x['excerpt'])

    def test_single_index_stroke_and_brain_imaging(self):
        diagnosis = 'The patient was discharged with a diagnosis of acute ischemic stroke.'
        imaging = 'During that admission, brain MRI revealed an acute infarct.'
        note = diagnosis + '\n' + imaging
        original = read_json(R11.parent / 'round9' / 'notes.json')['sigir-201515']
        admitted = ('The patient was admitted for ischemic stroke.\n'
                    'During that admission, head CT was negative for intracranial hemorrhage.')
        for raw in (original, admitted, note, note.replace('ischemic', 'ischaemic')):
            with self.subTest(note=raw[:30]):
                result, items, spans = self.resolve(raw, '817')
                self.assertEqual(result['state'], 'MISSING_DATA')
                self.assertEqual(result['source_sentences'], [])
                self.assertEqual(result['evidence'], [])
                fact = result['facts']['neurologic_symptoms_nonvascular_origin_after_ct_or_mri']
                self.assertIsNone(fact['value'])
                related, = fact['related_findings']
                self.assertEqual(related['source_lines'], [0, 1])
                ref = related['resource']
                link, = (span for span in spans if span['resource'] == ref)
                self.assertEqual(link['sentences'], [0, 1])
                slices = [raw[start:end] for _, start, end in link['spans']]
                self.assertEqual(slices, [line.split('. ', 1)[-1] if line[:1].isdigit() else line
                                          for line in raw.splitlines()[:2]])
                self.assertEqual(link['excerpt'], ' | '.join(slices))
                observation, = (item for item in items
                                if item['resourceType'] + '/' + item['id'] == ref)
                self.assertIs(observation['valueBoolean'], True)
                self.assertIn('linked-brain-imaging', observation['code']['coding'][0]['code'])

        unrelated = 'During a different hospitalization, brain MRI revealed an acute infarct.'
        negatives = [
            imaging, diagnosis, 'Head CT showed no intracranial hemorrhage.',
            'She was hospitalized for cryptogenic stroke. During that admission, his brain MRI showed an acute infarct.',
            note.replace('acute ischemic stroke', 'suspected ischemic stroke'),
            note.replace('The patient', 'Her mother'), diagnosis + '\n' + unrelated,
            diagnosis + '\nDuring that admission, chest CT was normal.',
            diagnosis + '\nDuring that admission, brain MRI was planned.',
            note.replace('acute ischemic stroke', 'seizure'),
            note + '\nThe initial diagnosis was later revised to migraine.',
            note + '\nCurrent symptoms have a nonvascular cause.',
            note + '\nShe now presents with a new episode of aphasia.',
            note.replace('a diagnosis of acute ischemic stroke', 'a stroke mimic'),
            note + '\nFamily history:\nHer sister had new symptoms.',
            note.replace('an acute infarct.', 'an acute infarct in another patient.'),
        ]
        for raw in negatives:
            with self.subTest(note=raw):
                result, _, _ = self.resolve(raw, '817')
                self.assertEqual(result['state'], 'MISSING_DATA')
                self.assertFalse(result['evidence'])

    def test_stroke_episode_location_and_revisions(self):
        diagnosis = 'The final diagnosis for this admission was an ischemic stroke.'
        scan = 'During this admission, head CT demonstrated cerebral infarction.'
        pairs = [
            (['The patient was seen for chest pain.', scan, diagnosis,
              'Follow-up scheduled in two weeks.'], [1, 2]),
            (['Vitals: BP 126/72 mm Hg.', 'Assessment: ' + diagnosis, scan,
              'Labs: Sodium 139 mmol/L.', 'Medications: ramipril 5 mg daily.'], [1, 2]),
            ([diagnosis, scan, 'The patient reports a rash.', 'CBC was unremarkable.',
              'Routine outpatient appointment arranged.'], [0, 1]),
        ]
        for lines, cited in pairs:
            raw = '\n'.join(lines)
            with self.subTest(raw=raw):
                result, _, spans = self.resolve(raw, '817')
                self.assertEqual(result['state'], 'MISSING_DATA')
                self.assertFalse(result['evidence'])
                fact = result['facts']['neurologic_symptoms_nonvascular_origin_after_ct_or_mri']
                related, = fact['related_findings']
                self.assertEqual(related['source_lines'], cited)
                ref = related['resource']
                record, = (r for r in spans if r['resource'] == ref)
                self.assertEqual([raw[a:b] for _,a,b in record['spans']],
                                 [lines[i].removeprefix('Assessment: ') for i in cited])

        for extra in ('This diagnosis was later withdrawn.', 'It was migraine instead.',
                      'The patient is now unable to speak.', 'Second patient: an ischemic stroke.',
                      'Vitals: BP 115/80 but she now has left-sided weakness.',
                      'Labs: Her symptoms were due to hypoglycemia.',
                      'Medications: The diagnosis was corrected.',
                      'There was a separate neurologic episode.', 'This account is incomplete.',
                      diagnosis, scan):
            with self.subTest(extra=extra):
                result, _, _ = self.resolve('\n'.join((diagnosis, scan, extra)), '817')
                self.assertEqual(result['state'], 'MISSING_DATA')

    def test_explicit_post_imaging_attribution(self):
        vascular = ('After reviewing the brain MRI, neurology attributed the presenting symptoms '
                    'to an ischemic stroke.')
        nonvascular = ('After the head CT, the final assessment attributed the presenting '
                       'neurologic symptoms to a nonvascular cause.')
        label = ('Post-CT or MRI neurologic assessment / '
                 'Presenting neurologic symptoms established as nonvascular')
        pair = ('The patient was admitted for ischemic stroke.\n'
                'During that admission, brain MRI was completed.')
        for raw, state, cited in [(vascular, 'MET', [0]), (nonvascular, 'NOT_MET', [0]),
                                  (pair + '\n' + vascular, 'MET', [2]),
                                  (label + ': yes.', 'NOT_MET', [0]), (label + ': no.', 'MET', [0])]:
            with self.subTest(raw=raw):
                result, _, _ = self.resolve(raw, '817')
                self.assertEqual(result['state'], state)
                self.assertEqual(result['source_sentences'], cited)
        for raw in (vascular.replace('presenting symptoms', 'remote symptoms'),
                    vascular.replace('attributed', 'might attribute'), vascular.replace('After', 'Before'),
                    vascular.replace('presenting symptoms', "her sister's presenting symptoms"),
                    nonvascular.replace('head CT', 'planned head CT'),
                    nonvascular.replace('nonvascular cause', 'possible nonvascular cause'),
                    vascular + '\nThe assessment was subsequently withdrawn.',
                    vascular + '\n' + nonvascular):
            with self.subTest(raw=raw):
                result, _, _ = self.resolve(raw, '817')
                self.assertEqual(result['state'], 'MISSING_DATA')
                self.assertFalse(result['evidence'])
        conflict, _, _ = self.resolve(vascular + '\n' + label + ': yes.', '817')
        self.assertEqual(conflict['state'], 'MISSING_DATA')
        self.assertEqual(len(conflict['facts']['neurologic_symptoms_nonvascular_origin_after_ct_or_mri']['evidence']), 2)

    def test_sources_and_group(self):
        _,items,_=self.resolve('CT chest today showed pulmonary embolism.')
        spec=self.pack['rules']['435']['rule']['facts']['chest_ct_showed_pulmonary_thromboembolism']
        p=next(r for r in items if r['resourceType']=='Provenance')
        for ex in p['entity'][0]['extension']:
            if ex['url']==END:ex['valueInteger']=10000
        self.assertEqual(NativeChart(items,'Patient/demo',self.pack['contracts']).read(spec)[1],'MISSING_DATA')
        with self.assertRaises(ValueError):plain_chart('demo','A group of 14 people is being screened.','2026-01-01T00:00:00Z')

    def test_polarity_and_family(self):
        for note in ['Family history:\n\nShe is on a mechanical ventilator.',
                     'His sister was admitted. She remains on a mechanical ventilator.',
                     'If he deteriorates he may need mechanical ventilation.']:
            _,items,_=self.resolve(note,'187')
            f=self.pack['rules']['187']['rule']['facts']['receiving_mechanical_ventilation']
            self.assertEqual(NativeChart(items,'Patient/demo',self.pack['contracts']).read(f)[1],'MISSING_DATA')
        _,_,spans=self.resolve('He denies fever and reports cough and rash.')
        self.assertFalse(any('rash' in s.get('resource','') for s in spans))
        b,_=plain_chart('demo','He denies fever and reports cough and rash.','2026-01-01T00:00:00Z')
        ob=[e['resource'] for e in b['entry'] if e['resource']['resourceType']=='Observation']
        self.assertFalse(any(x['code']['text']=='reported rash' and x['valueBoolean'] is False for x in ob))

if __name__=='__main__':unittest.main()
