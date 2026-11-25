from copy import deepcopy
import unittest

from user_clarified import (HERE, R11, clarify, read_json, screen_user_clarified,
                            validated_interpretation, verify)


class UserClarificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = verify(read_json(R11 / 'compiled.json'))
        cls.answer = read_json(HERE / 'user_answer.json')

    def evaluate(self, bundle, patient, answer):
        return screen_user_clarified([e['resource'] for e in bundle['entry']], 'Patient/' + patient,
                                     self.pack, clarify.STUDY, clarify.CASE, answer)

    def test_three_cited_symptoms_and_absent_original_document_fields(self):
        trace = self.evaluate(clarify.frozen_bundle(), clarify.PATIENT, self.answer)
        row = trace['criteria'][clarify.CASE]
        self.assertEqual(row['state'], 'MET')
        right = {'dysmenorrhea': 'severe premenstrual and menstrual pelvic pain',
                 'menorrhagia': 'heavy, irregular periods',
                 'metrorrhagia': 'occasional spotting between periods'}
        for term, quote in right.items():
            self.assertIs(row['facts'][term]['value'], True)
            ref, = row['facts'][term]['evidence']
            self.assertEqual(row['source_spans'][ref]['quote'], quote)
        self.assertIsNone(row['facts']['dyspareunia']['value'])
        self.assertIsNone(row['facts']['chronic_pelvic_pain']['value'])
        self.assertNotIn('pelvic_congestion_diagnosed', row['facts'])
        self.assertNotIn('protocol_decision', trace)
        self.assertFalse(trace['user_clarification']['source_authority_verified'])
        self.assertIsNone(trace['user_clarification']['governing_protocol_clause'])
        self.assertEqual(self.pack['rules'][clarify.CASE]['rule']['expression'].keys(), {'hold'})

    def test_other_subject_qualifies_with_only_one_symptom(self):
        for term in clarify.SYMPTOMS:
            text = 'A 38 year old woman reports ' + clarify.TERMS[term][0] + '.'
            chart, _ = clarify.plain_chart('patient-x', text, '2026-01-01T00:00:00Z')
            self.assertEqual(self.evaluate(chart, 'patient-x', self.answer)['criteria'][clarify.CASE]['state'], 'MET')

    def test_no_answer_or_no_patient_evidence(self):
        self.assertEqual(self.evaluate(clarify.frozen_bundle(), clarify.PATIENT, None)['criteria'][clarify.CASE]['state'], 'AUTHORING_HOLD')
        for note, state in [
            ('The patient is a woman.\nHer mother reports dysmenorrhea.', 'MISSING_DATA'),
            ('A 38 year old woman denies dysmenorrhea.', 'MISSING_DATA'),
            ('A 38 year old woman denies dysmenorrhea, dyspareunia, chronic pelvic pain, menorrhagia and metrorrhagia.', 'NOT_MET')]:
            chart, _ = clarify.plain_chart('patient-x', note, '2026-01-01T00:00:00Z')
            self.assertEqual(self.evaluate(chart, 'patient-x', self.answer)['criteria'][clarify.CASE]['state'], state)

    def test_user_cannot_accidentally_upgrade_or_rescope_answer(self):
        for key, value in [('answer','No'), ('answer',None), ('question','Yes?'), ('protocol_id','other'),
                           ('source_authority_verified',True), ('governing_protocol_version','1.0'),
                           ('governing_protocol_clause','unknown'), ('source_role','investigator'),
                           ('authority_id','unverified'), ('criterion','707')]:
            altered = deepcopy(self.answer)
            altered[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validated_interpretation(altered, self.pack, clarify.STUDY, clarify.CASE)
        with self.assertRaises(ValueError):
            screen_user_clarified([], 'Patient/abc', self.pack, 'other-study', clarify.CASE, self.answer)


if __name__ == '__main__':
    unittest.main()
