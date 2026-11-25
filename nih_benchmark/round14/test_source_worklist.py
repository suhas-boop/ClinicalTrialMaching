"""Validate grouping at the same chart-screen entry point used for matching."""
from contextlib import closing
from copy import deepcopy
import unittest

from source_worklist import (HERE, R9, SCOPE, build_worklist, read_json,
                             replay_scopes, request_id)
from match import open_chart, screen, search


class SourceWorklistTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = read_json(HERE.parent / 'round11/compiled.json')
        cls.assignments = read_json(R9 / 'assignments.json')
        subjects = {row['case']: row['subject'] for row in read_json(R9 / 'export/cases.json')}
        traces = {}
        with closing(open_chart(R9 / 'export/chart.sqlite')) as db:
            for row in cls.assignments:
                case, subject = str(row['annotation_id']), subjects[row['patient']]
                traces[case] = screen(search(db, subject), subject, cls.pack, row['study'], case)
        cls.scopes = list(replay_scopes(traces, cls.assignments, cls.pack, subjects))
        cls.grouped = build_worklist(cls.scopes, cls.pack)
        cls.by_case = {next(iter(t['criteria'])): (s, t) for s, t in cls.scopes}

    def test_no_request_membership_or_selector_lost(self):
        expected = {(tuple(scope[k] for k in SCOPE), q['route'], q['id'], cid)
                    for scope, trace in self.scopes for q in trace['requests'] for cid in q['criteria']}
        received = set()
        for group in self.grouped['groups']:
            coords = tuple(group['scope'][k] for k in SCOPE)
            for row in group['requests']:
                if 'alternate_forms_by_criterion' in row:
                    for cid, forms in row['alternate_forms_by_criterion'].items():
                        self.assertEqual(row['facts_by_criterion'][cid], [form['fact'] for form in forms])
                        for form in forms:
                            self.assertEqual(form['selectors'], self.pack['contracts'][form['contract']]['native'])
                else:
                    self.assertEqual(row['selectors'], self.pack['contracts'][row['contract']]['native'])
                self.assertEqual(set(row['criteria']), set(row['facts_by_criterion']))
                for cid in row['criteria']:
                    received.add((coords, 'retrieve_record', row['request_id'], cid))
        for row in self.grouped['other_requests']:
            received.update((tuple(row['scope'][k] for k in SCOPE), row['route'], row['request_id'], cid)
                            for cid in row['criteria'])
        self.assertEqual(expected, received)
        self.assertEqual(len(expected), self.grouped['request_criterion_links'])

    def test_source_unit_forms_share_one_request_and_retain_selectors(self):
        scope, trace = self.by_case['218']
        groups = build_worklist([(scope, trace)], self.pack)['groups']
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['source_family'], 'laboratory report')
        self.assertEqual(len(groups[0]['requests']), 1)
        row = groups[0]['requests'][0]
        self.assertEqual(row['request_id'], trace['requests'][0]['id'])
        forms = row['alternate_forms_by_criterion']['218']
        self.assertEqual({form['fact'] for form in forms}, {'serum_creatinine_mg_dl', 'serum_creatinine_umol_l'})
        for form in forms:
            self.assertEqual(form['selectors'], self.pack['contracts'][form['contract']]['native'])
        damaged = deepcopy(trace)
        del damaged['criteria']['218']['facts'][forms[0]['fact']]
        with self.assertRaises(ValueError):
            build_worklist([(scope, damaged)], self.pack)

    def test_ranking_and_alternatives(self):
        priorities = [len(g['affected_criteria']) for g in self.grouped['groups']]
        self.assertEqual(priorities, sorted(priorities, reverse=True))
        shared = [g for g in self.grouped['groups'] if g['source_family'] == 'vital-sign flowsheet'
                  and {'186', '187'} <= set(g['affected_criteria'])]
        self.assertEqual(len(shared), 1)
        expression = self.grouped['rules'][shared[0]['scope']['study']]['187']['expression']
        self.assertEqual(expression, self.pack['rules']['187']['rule']['expression'])
        self.assertEqual({n['fact'] for n in expression['any']},
                         {'respiratory_rate', 'paco2_mmhg', 'receiving_mechanical_ventilation'})

    def test_wrong_scope_and_forged_selector_rejected(self):
        scope, trace = self.by_case['187']
        for key in SCOPE:
            with self.subTest(key=key), self.assertRaises(ValueError):
                build_worklist([(dict(scope, **{key: scope[key] + '_other'}), trace)], self.pack)
        damaged = deepcopy(trace)
        damaged['requests'][0]['request'] += ' altered'
        with self.assertRaises(ValueError):
            build_worklist([(scope, damaged)], self.pack)

    def test_separate_requests_for_distinct_subject_episode_cutoff(self):
        scope, trace = self.by_case['187']
        inputs = [(scope, trace)]
        for key in ('subject','episode','encounter','cutoff'):
            variant_scope = dict(scope, **{key: scope[key] + '_other'})
            variant_trace = deepcopy(trace)
            for row in variant_trace['requests']:
                contract_id = next(c for c in self.pack['rules']['187']['bindings'].values()
                                   if request_id(scope, c) == row['id'])
                row['id'] = request_id(variant_scope, contract_id)
            inputs.append((variant_scope, variant_trace))
        result = build_worklist(inputs, self.pack)
        self.assertEqual(len(result['groups']), len(inputs) * 3)
        self.assertEqual(result['unique_scoped_record_requests'], len(inputs) * 3)

    def test_duplicate_delivery_is_idempotent(self):
        self.assertEqual(build_worklist([*self.scopes, *self.scopes], self.pack), self.grouped)


if __name__ == '__main__':
    unittest.main()
