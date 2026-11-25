"""Run a sponsor-defined fever-duration gate using the ordinary FHIR rule engine."""
import argparse
import base64
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
sys.path.insert(0, str(BENCH / 'round16'))
from literal_scope import frozen_assignments
from catalog import FACTS, contract, fact, selector, verify
from match import screen
from native import NativeChart
from run import fingerprint

STUDY = 'NCT02618655'
SOURCE = BENCH / 'round8' / 'context' / (STUDY + '.json')
DIGEST = 'fbaf17afb1e459dff97f0ff2a1a5d86e09a189a6a1a2242678c990703a76bb50'
TEXT = 'patients have fever more than one week'
GATE = 'inclusion-fever-duration'
KEY = 'current_fever_episode_duration_days'
SCOPE = 'Current fever duration at the patient presentation'
READER = 'current-symptom-duration-r1'

# Accept patient-owned present-tense history, exact durations, and simple symptom lists.
# A shared suffix requires corroboration if its immediate neighbour is another symptom.
DEMOGRAPHIC = r'an? (?:\d{1,3}[ -](?:year|month)[ -]old )?(?:male|female|woman|man|girl|boy|child)'
OWNER = rf'(?:the patient|{DEMOGRAPHIC})'
VISIT = (r'presents(?: in (?:January|February|March|April|May|June|July|August|September|October|November|December))?'
         r'(?: to (?:the )?(?:ER|ED|emergency department|clinic))? with')
FEVER = r'(?:(?:high )?fever)(?: up to \d{2}(?:\.\d+)?\s*°?\s*[CF])?'
OTHER = r'(?:cough|dyspnea|headache|chills|irritability|malaise)'
SYMPTOMS = rf'(?P<fever>{FEVER})(?P<others>(?:(?:,\s*(?:and\s+)?| and ){OTHER})*)'
DURATION = r'(?P<n>\d{1,3})\s+(?P<u>days?|weeks?)'
DIRECT = re.compile(rf'{OWNER} (?:{VISIT}|has had|reports) (?:a )?{SYMPTOMS}(?P<all>,? all)? for {DURATION}[.]?', re.I)
PREFIX = re.compile(rf'{OWNER} (?:{VISIT}|reports) {DURATION} of {SYMPTOMS}[.]?', re.I)
ONSET = re.compile(rf"(?:parents report that |the patient reports that )?prior to the onset of fever and (?P<last>{OTHER}), "
                   r"(?P<owner>he|she|the patient) had (?:loose stools|diarrhea|a headache|nausea)[.]?", re.I)
FEVER_MENTION = re.compile(r'\b(?:fevers?|feverish|afebrile|febrile|pyrexia|defervesce\w*)\b', re.I)
EPISODE_QUALIFIER = re.compile(
    r'\b(?:relapsed|recurred|remitted|intermittent|recurrent|waxing|waning|second episode|'
    r'symptom[- ]free|prior episode|previous episode|symptoms? (?:persisted|returned|resolved)|'
    r'(?:this|it|the illness|the symptoms?) (?:began|started)|earlier onset|started earlier|'
    r'(?:first|other|third|fourth|another) episode|in fact|on further questioning|'
    r'earlier than reported|onset (?:unknown|unclear|uncertain)|correction|corrected)\b', re.I)
OTHER_CONTEXT = re.compile(
    r'\b(?:another patient|another child|roommate|household contact|other child|sibling|cousin|'
    r'his (?:mother|father|brother|sister)|her (?:mother|father|brother|sister))\b|'
    r'^(?:family|past medical|past|exposure) history\b|^.+:\s*$', re.I)


def protocol(path=SOURCE):
    raw = Path(path).read_bytes()
    if sha256(raw).hexdigest() != DIGEST:
        raise ValueError('Fever gate requires the reviewed registry version')
    section = json.loads(raw)['protocolSection']
    criteria = section['eligibilityModule']['eligibilityCriteria']
    first_inclusion, separator, _ = criteria.partition('\n\nExclusion Criteria:')
    if (section['identificationModule']['nctId'] != STUDY or not separator
            or first_inclusion.splitlines()[:3] != ['Inclusion Criteria:', '', '* ' + TEXT]):
        raise ValueError('Mandatory fever-duration item could not be verified')
    start = criteria.index(TEXT)
    return dict(trial_id=STUDY, criterion_type='inclusion', criterion_text=TEXT,
                registry_url='https://clinicaltrials.gov/study/' + STUDY,
                registry_sha256=DIGEST, registry_date=section['statusModule']['lastUpdatePostDateStruct']['date'],
                location='protocolSection.eligibilityModule.eligibilityCriteria / inclusion item 1',
                start=start, end=start + len(TEXT))


def catalog(source):
    spec = fact(KEY, 'number', 'd', scope=SCOPE)
    cid = contract(spec)
    rule = dict(expression={'fact':KEY, 'op':'gt', 'value':7}, facts={KEY:spec})
    entry = dict(rule=rule, bindings={KEY:cid}, source=source)
    definition = dict(spec=spec, normalized_system=FACTS,
                      native=[selector('DocumentReference', KEY, SCOPE, READER)])
    pack = dict(format_version=1, rules={GATE:entry}, contracts={cid:definition}, measurement_families={})
    return verify(dict(**pack, sha256=fingerprint(pack)))


def note_lines(body):
    """Retain offsets in Unicode characters relative to the original FHIR attachment."""
    start = 0
    for i, raw in enumerate(body.splitlines(keepends=True)):
        content = raw.rstrip()
        prefix = re.match(r'^\s*(?:\d+\.\s+)?', content).end()
        if prefix < len(content):
            yield content[prefix:], dict(line=i, start=start+prefix, end=start+len(content))
        start += len(raw)


class SymptomDuration:
    def __init__(self, resources, subject, study):
        view = NativeChart(resources, subject, {}, study)
        self.digest, self.spans, self.value = view.hash, {}, None
        documents = [r for r in resources if r['resourceType']=='DocumentReference']
        if (len(documents) != 1 or documents[0].get('modifierExtension') or documents[0].get('implicitRules')
                or len(documents[0].get('content', [])) != 1
                or documents[0]['content'][0]['attachment'].get('contentType') != 'text/plain'
                or [r['id'] for r in resources if r['resourceType']=='Patient'] != [subject.split('/',1)[1]]
                or any(r['resourceType']=='Group' or r.get('subject', {}).get('reference',subject)!=subject
                       for r in resources)):
            raise ValueError('Expected one verified individual and one plain-text current FHIR source')
        body = base64.b64decode(documents[0]['content'][0]['attachment']['data'], validate=True).decode()
        lines = list(note_lines(body))
        if not lines or EPISODE_QUALIFIER.search(body):
            return
        presentation, anchor = lines[0]
        prefix = PREFIX.fullmatch(presentation)
        observed = prefix or DIRECT.fullmatch(presentation)
        if not observed:
            return
        spans = [anchor]
        suffix_endpoint = re.findall(OTHER, observed['others'], re.I)
        corroboration_needed = not prefix and bool(suffix_endpoint) and not observed['all']
        for text, position in lines[1:]:
            if OTHER_CONTEXT.search(text):
                return
            if not FEVER_MENTION.search(text):
                continue
            shared = ONSET.fullmatch(text)
            if not (corroboration_needed and shared and shared['last'].lower()==suffix_endpoint[-1].lower()):
                # Any other description of fever in this bounded reader needs reconciliation.
                return
            owner = shared['owner'].lower()
            if owner != 'the patient':
                referent = r'\b(?:boy|male|man)\b' if owner == 'he' else r'\b(?:girl|female|woman)\b'
                if not re.search(referent, presentation[:observed.start('fever')], re.I):
                    return
            spans.append(position)
        if corroboration_needed and len(spans) < 2:
            return
        self.value = int(observed['n']) * (7 if observed['u'].lower().startswith('week') else 1)
        for span in spans:
            start,end = span['start'],span['end']
            ref = f"{view.source}#sha256={view.hash}&line={span['line']}&start={start}&end={end}"
            self.spans[ref] = dict(**span, document=view.source, quote=body[start:end])

    def read(self, spec):
        if spec['label']!=KEY or spec.get('unit')!='d':
            return None,'BINDING_HOLD',[],'Unknown symptom-duration contract.'
        if self.value is None:
            return None,'MISSING_DATA',[],'Obtain the onset or duration of this fever episode at presentation.'
        return self.value,None,list(self.spans),'Current fever episode duration in days.'


def screen_fever(resources, subject, study, *, expected_source_sha256=None):
    if study != STUDY:
        return None
    source = protocol()
    pack = catalog(source)
    reader = SymptomDuration(resources, subject, study) if subject.startswith('Patient/') else None
    result = screen(resources, subject, pack, study, GATE, document_readers={READER:reader} if reader else {})
    if expected_source_sha256 is not None and result['source_sha256'] != expected_source_sha256:
        raise ValueError('Unexpected fever gate patient source digest')
    verdict = result['criteria'][GATE]
    refs = verdict['evidence']
    return dict(study=study, subject=subject, gate=GATE, state=verdict['state'],
                source_sha256=result['source_sha256'], evidence=refs,
                source_spans={ref:reader.spans[ref] for ref in refs},
                protocol=source, value_days=verdict['facts'].get(KEY,{}).get('value'),
                operator='gt', threshold_days=7, catalog_sha256=pack['sha256'])


def replay():
    gates, rows, pairs = {}, 0, defaultdict(list)
    for row, subject, resources, digests in frozen_assignments():
        rows += 1
        pair = subject, row['study']
        pairs[pair].append(row['annotation_id'])
        if row['study'] == STUDY and pair not in gates:
            gates[pair] = screen_fever(resources, *pair, expected_source_sha256=digests[subject])
    for pair, result in gates.items():
        result['linked_frozen_criteria'] = sorted(pairs[pair])
    return dict(assignments=rows, patient_study_pairs=len(pairs), gates=list(gates.values()),
                registry_sha256=DIGEST, frozen_criterion_scores_modified=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path)
    args = parser.parse_args()
    receipt = json.dumps(replay(),indent=2,ensure_ascii=False)+'\n'
    if args.out:
        args.out.write_text(receipt)
    else:
        print(receipt,end='')
