"""Reproduce the prior benchmark-only literal-cohort interpretation on verified vignettes."""
import base64
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH/'round12'))
from intake import benchmark_chart, plain_chart
from screen import R11, read_json, screen, verify
from native import NativeChart
from catalog import contract, fact, selector
from run import fingerprint

POLICY = 'trialgpt-literal-adult-description-r2'
RULE_SOURCE = ('NCT01745731', 'exclusion',
               'Pregnant women or women of childbearing age who do not have adequate contraception.',
               '0ab88ce90e531df67bf22c3823087705957754cc68b1a996e51f8fd5063a825b')
TARGET = 'in_protocol_women_population'
SCOPE = 'Adult cohort as explicitly described in this synthetic vignette for the registered exclusion'
NEW = 'synthetic_vignette_literal_adult_women_cohort'
AUTHOR = 'https://www.clinicaltrialsregister.eu/ctr-search/trial/2009-017793-20/ES'
HEADER = re.compile(r'^(?:0\.\s*)?an? (?P<age>\d{1,3})[- ]year[- ]old '
                    r'(?:(?:white|black|asian|caucasian|african[- ]american) )?'
                    r'(?P<word>man|male)\s+(?:presents?\b|presented\b|with (?:a )?history of\b)', re.I)
# Withhold the optional outside-cohort inference for a second descriptor, conflicting
# pronoun, reproductive statement, or relevant anatomy anywhere in the whole note.
CONTEXT = re.compile(r"\b(?:she|her|hers|woman|women|girl|female|gestat\w*|pregnan\w*|"
                     r"reproduc\w*|gravid\w*|menstr\w*|menses|menarc\w*|ovar\w*|uter\w*|"
                     r"amenorr\w*|contracept\w*|hyster\w*|matern\w*|childbear\w*|"
                     r"intersex|gender|trans(?:gender|sexual|masculine|feminine)?|"
                     r"non[- ]?binary|assigned|identif\w* as|sex at birth|capable of carrying)\b", re.I)


def literal_catalog(pack, criterion):
    entry = pack['rules'][criterion]
    source = entry['source']
    pin = (source['trial_id'], source['criterion_type'], source['criterion_text'],
           source.get('registry', {}).get('registry_sha256'))
    if pin != RULE_SOURCE:
        return None
    candidate = deepcopy(pack)
    edit = candidate['rules'][criterion]
    current = edit['rule']
    outer = current['expression'].get('not', {}).get('all', [])
    if not outer or outer[0] != {'fact':TARGET}:
        raise ValueError('Source-qualified scope guard required')
    old = edit['bindings'].pop(TARGET)
    del current['facts'][TARGET]
    spec = fact(NEW, scope=SCOPE)
    cid = contract(spec)
    current['facts'][NEW] = spec
    outer[0] = {'fact':NEW}
    edit['bindings'][NEW] = cid
    selectors = deepcopy(pack['contracts'][old])
    selectors['spec'] = spec
    selectors['native'].append(selector('Observation','woman','note abstraction','boolean'))
    candidate['contracts'][cid] = selectors
    edit['source']['synthetic_scope_policy'] = {'policy':POLICY, 'registry':AUTHOR,
            'source_field':'explicit adult demographic description at presentation',
            'assumption':'For this synthetic eligibility question, the written male/man presentation descriptor places the subject outside both branches of the women-qualified exclusion.'}
    candidate['sha256'] = fingerprint({k:v for k,v in candidate.items() if k!='sha256'})
    return verify(candidate)


def screen_synthetic_note(resources, subject, pack, study, criterion, allowed_note_hashes):
    """The caller supplies individual synthetic subject -> frozen source SHA256."""
    strict = screen(resources, subject, pack, study, criterion)
    result = dict(policy=POLICY, used=False, strict_state=strict['criteria'][criterion]['state'], trace=strict)
    if (subject not in allowed_note_hashes or not subject.startswith('Patient/') or study!=RULE_SOURCE[0]
            or result['strict_state']!='MISSING_DATA'):
        return result
    if len([r for r in resources if r['resourceType']=='DocumentReference']) != 1:
        return result
    candidate = literal_catalog(pack, criterion)
    if candidate is None:
        return result
    if allowed_note_hashes[subject] != strict['source_sha256']:
        raise ValueError('Synthetic source identity or content mismatch')
    view = NativeChart(resources, subject, candidate['contracts'], study)
    doc = next(r for r in resources if 'DocumentReference/'+r['id']==view.source and r['resourceType']=='DocumentReference')
    raw = base64.b64decode(doc['content'][0]['attachment']['data'], validate=True).decode()
    header = HEADER.match(raw.splitlines()[0].strip())
    if not header or not 18 <= int(header['age']) <= 120 or CONTEXT.search(raw):
        return result
    current = strict['criteria'][criterion]['facts']
    if any(v['evidence'] or v.get('value') is not None for v in current.values()):
        return result
    if any(r['resourceType']=='Patient' and r.get('gender') not in (None,'unknown') for r in resources):
        return result
    if any(r['resourceType']=='Observation' and
           any(code.get('code') in ('pregnant','current-pregnancy','explicit_woman_description',
                                    'screening_pregnancy_exclusion_documented_inapplicable','woman_of_childbearing_age',
                                    'in_protocol_women_population') for code in r.get('code',{}).get('coding',[]))
           for r in resources):
        return result
    trace = screen(resources, subject, candidate, study, criterion)
    conclusion = trace['criteria'][criterion]
    guard = conclusion['facts'][NEW]
    if (conclusion['state']!='MET' or guard['value'] is not False or not guard['evidence']
            or set(conclusion['evidence'])!=set(guard['evidence'])
            or any(view.refs.get(x)!=[0] for x in guard['evidence'])):
        return result
    return dict(policy=POLICY,used=True,strict_state=result['strict_state'],trace=trace,
                assumption=candidate['rules'][criterion]['source']['synthetic_scope_policy']['assumption'],
                source=doc['id'], source_sha256=view.hash, line=0, literal=header['word'],
                source_excerpt=raw.splitlines()[0],protocol=RULE_SOURCE[0], secondary_registry=AUTHOR)


def frozen_assignments():
    """Yield the same verified patient resources to every screening arm."""
    notes = read_json(BENCH/'round9/notes.json')
    subjects = {v['case']:v['subject'] for v in read_json(BENCH/'round9/export/cases.json')}
    hashes = read_json(BENCH/'round9/note_hashes.json')
    if any(sha256(note.encode()).hexdigest() != hashes.get(pid) for pid,note in notes.items()):
        raise ValueError('Frozen source note content changed.')
    approved = {subjects[p]:digest for p,digest in hashes.items()}
    charts = {}
    for row in read_json(BENCH/'round9/assignments.json'):
        pid = row['patient']
        subject = subjects[pid]
        if pid not in charts:
            bundle, _ = benchmark_chart(pid, notes[pid], '2026-01-01T00:00:00Z')
            charts[pid] = [e['resource'] for e in bundle['entry']]
        yield row, subject, charts[pid], approved


def replay():
    pack = verify(read_json(R11/'compiled.json'))
    predictions = {}
    for row, subject, resources, approved in frozen_assignments():
        key = str(row['annotation_id'])
        predictions[key] = screen_synthetic_note(resources,subject,pack,row['study'],key,approved)
    return predictions

if __name__=='__main__':
    raw = replay()
    print(json.dumps({k:v for k,v in raw.items() if v['used']},indent=2))
