"""Group screen requests by suggested document type while preserving rule logic."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'round11'))
from match import R9, fingerprint, read_json, verify
from record_search import record_family

SCOPE = ('subject', 'episode', 'encounter', 'study', 'study_version', 'cutoff', 'source_sha256')


def current_version(pack, study):
    entries = {cid: {key: entry[key] for key in ('rule', 'source')}
               for cid, entry in pack['rules'].items() if entry['source']['trial_id'] == study}
    if not entries:
        raise ValueError('Unknown study')
    return fingerprint(entries)


def request_id(scope, requirement, route='retrieve_record'):
    if route == 'identify_subject':
        parts = [scope['subject'], scope['source_sha256'], route]
    else:
        parts = [scope['study'], scope['study_version'], route, requirement]
        if route not in ('engineering', 'protocol_review'):
            parts.extend(scope[key] for key in ('subject', 'episode', 'encounter', 'cutoff'))
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


def replay_scopes(traces, assignments, pack, subjects=None):
    """Restore the same scope that the benchmark's normal match.screen used."""
    by_case = {str(row['annotation_id']): row for row in assignments}
    if subjects is None:
        subjects = {row['case']: row['subject'] for row in read_json(R9 / 'export/cases.json')}
    versions = {}
    for case, trace in traces.items():
        assignment = by_case[case]
        study = assignment['study']
        if list(trace['criteria']) != [case]:
            raise ValueError('Trace and assigned criterion disagree')
        if study not in versions:
            versions[study] = current_version(pack, study)
        # The source digest is the cutoff of the frozen single-note benchmark.
        # A normal longitudinal screen calls build_worklist with its actual cutoff.
        scope = dict(subject=subjects[assignment['patient']], episode='benchmark presentation',
                     encounter='benchmark vignette', study=study, study_version=versions[study],
                     cutoff=trace['source_sha256'], source_sha256=trace['source_sha256'])
        yield scope, trace


def measurement_nodes(node):
    if isinstance(node, dict):
        if 'same_measurement' in node:
            yield node
        else:
            for child in node.values():
                yield from measurement_nodes(child)
    elif isinstance(node, list):
        for child in node:
            yield from measurement_nodes(child)


def measurement_bindings(pack, scope, trace, cid, request):
    description = request['request']
    if request['route'] != 'retrieve_record' or request_id(scope, description) != request['id']:
        return []
    entry = pack['rules'][cid]
    alternatives = set()
    for key in ('applies', 'expression'):
        for node in measurement_nodes(entry['rule'].get(key)):
            if pack['measurement_families'][node['family']]['request'] == description:
                alternatives.add(tuple(sorted(form['fact'] for form in node['same_measurement'])))
    if len(alternatives) != 1:
        raise ValueError('Shared request cannot be traced to a unique measurement definition')
    forms = []
    for name in next(iter(alternatives)):
        contract_id = entry['bindings'][name]
        fact = trace['criteria'][cid]['facts'].get(name, {})
        if fact.get('contract') != contract_id:
            raise ValueError('Shared measurement is missing an original binding')
        forms.append((name, contract_id))
    return forms


def bound_facts(pack, scope, trace, cid, request):
    entry = pack['rules'][cid]
    candidates = []
    for name, contract_id in entry['bindings'].items():
        if request_id(scope, contract_id, request['route']) != request['id']:
            continue
        contract = pack['contracts'][contract_id]
        fact = trace['criteria'][cid]['facts'].get(name, {})
        if fact.get('contract') != contract_id or contract['spec']['scope'] != request['request']:
            continue
        candidates.append((name, contract_id))
    if not candidates or len({contract for _, contract in candidates}) != 1:
        raise ValueError('Request scope, contract or selector mismatch')
    return candidates


def build_worklist(scoped_traces, pack):
    """Accept (scope, match.screen output) pairs. Never reads outcome labels."""
    verify(pack)
    groups, other, input_links, rules, versions = {}, {}, set(), {}, {}
    for scope, trace in scoped_traces:
        if any(not isinstance(scope.get(key), str) or not scope[key] for key in SCOPE):
            raise ValueError('Incomplete screening scope')
        coords = tuple(scope[key] for key in SCOPE)
        study = scope['study']
        if study not in versions:
            versions[study] = current_version(pack, study)
        if (scope['study_version'] != versions[study] or trace['catalog_sha256'] != pack['sha256']
                or trace['source_sha256'] != scope['source_sha256']):
            raise ValueError('Catalog, source or study-version mismatch')
        for request in trace['requests']:
            route, qid, description = request['route'], request['id'], request['request']
            if not request['criteria']:
                raise ValueError('Request lacks criterion')
            for cid in request['criteria']:
                entry = pack['rules'][cid]
                if cid not in trace['criteria'] or entry['source']['trial_id'] != study:
                    raise ValueError('Request points to the wrong study or criterion')
                input_links.add((coords, qid, cid))
                if route == 'protocol_review' or route == 'identify_subject':
                    if request_id(scope, description, route) != qid:
                        raise ValueError('Request scope mismatch')
                else:
                    forms = measurement_bindings(pack, scope, trace, cid, request)
                    facts = forms or bound_facts(pack, scope, trace, cid, request)
                if route != 'retrieve_record':
                    row = other.setdefault((coords, qid), dict(scope=dict(scope), request_id=qid,
                                           route=route, request=description, criteria=set()))
                    row['criteria'].add(cid)
                    continue
                family = record_family(description)
                group = groups.setdefault((coords, family), dict(scope=dict(scope), source_family=family,
                                           requests={}, affected_criteria=set()))
                row = group['requests'].setdefault(qid, dict(request_id=qid, request=description,
                                                   facts_by_criterion={}, criteria=set()))
                if forms:
                    # One document request, with separate original selectors and
                    # source-unit thresholds for each accepted reporting form.
                    row.setdefault('alternate_forms_by_criterion', {})[cid] = [
                        dict(fact=name, contract=contract_id,
                             selectors=pack['contracts'][contract_id]['native'])
                        for name, contract_id in forms]
                else:
                    contract_id = facts[0][1]
                    row.update(contract=contract_id, selectors=pack['contracts'][contract_id]['native'])
                row['criteria'].add(cid)
                row['facts_by_criterion'][cid] = sorted(name for name, _ in facts)
                group['affected_criteria'].add(cid)
                rules.setdefault(study, {})[cid] = {
                    key: entry['rule'][key] for key in ('applies', 'expression') if key in entry['rule']}

    output, retained = [], set()
    for (coords, _), group in groups.items():
        group['requests'] = sorted(group['requests'].values(), key=lambda row: row['request_id'])
        for row in group['requests']:
            row['criteria'] = sorted(row['criteria'])
            retained.update((coords, row['request_id'], cid) for cid in row['criteria'])
        group['affected_criteria'] = sorted(group['affected_criteria'])
        output.append(group)
    for (coords, qid), row in other.items():
        row['criteria'] = sorted(row['criteria'])
        retained.update((coords, qid, cid) for cid in row['criteria'])
    if retained != input_links:
        raise ValueError('Lost request-to-criterion link during grouping')
    output.sort(key=lambda g: (-len(g['affected_criteria']), -len(g['requests']),
                               tuple(g['scope'][key] for key in SCOPE), g['source_family']))
    return dict(scope_fields=SCOPE, catalog_sha256=pack['sha256'],
                unique_scoped_record_requests=sum(len(g['requests']) for g in output),
                distinct_record_request_ids=len({r['request_id'] for g in output for r in g['requests']}),
                request_criterion_links=len(retained),
                routing_note='Suggested document families group retrieval only. Evaluate alternatives and exceptions with the original criterion expression.',
                groups=output, rules=rules, other_requests=sorted(other.values(), key=lambda row: (
                    row['route'], row['request_id'], tuple(row['scope'][key] for key in SCOPE))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('traces', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--catalog', type=Path, default=HERE.parent / 'round11/compiled.json')
    parser.add_argument('--assignments', type=Path, default=R9 / 'assignments.json')
    parser.add_argument('--subjects', type=Path, default=R9 / 'export/cases.json')
    args = parser.parse_args()
    pack = verify(read_json(args.catalog))
    subjects = {row['case']: row['subject'] for row in read_json(args.subjects)}
    scoped = replay_scopes(read_json(args.traces), read_json(args.assignments), pack, subjects)
    result = build_worklist(scoped, pack)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(dict(record_groups=len(result['groups']),
                          record_requests=result['distinct_record_request_ids'])))


if __name__ == '__main__':
    main()
