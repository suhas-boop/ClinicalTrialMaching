"""Apply an independently authorised study clarification to one source-verified TrialGPT case."""
import argparse
import base64
import json
import re
import sys
from collections import defaultdict
from datetime import date
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = HERE.parents[1]
sys.path.insert(0, str(BENCH / 'round12'))
from intake import benchmark_chart, plain_chart
from screen import read_json
from native import NativeChart
from eligibility_engine import validate
from author_rules import fact
from review import ReviewQueue
from run import fingerprint

STUDY, CASE, PATIENT = 'NCT02340533', '706', 'sigir-201510'
REGISTRY = BENCH/'round8/context'/f'{STUDY}.json'
SOURCE = read_json(BENCH/'round11/compiled.json')['rules'][CASE]['source']
DIGEST = SOURCE['registry']['registry_sha256']
SYMPTOMS = ['dysmenorrhea','dyspareunia','chronic_pelvic_pain','menorrhagia','metrorrhagia']
QUESTION = ('For this registered inclusion criterion, must the patient report any one, all five, or a different '
            'combination of the five symptoms? Do these symptoms alone establish the complaint, or must pelvic '
            'congestion be separately diagnosed? Can the current presenting complaint and a source description '
            'of the participant as a woman or female be used without an additional duration, scale or assessment? '
            'Identify the governing protocol version and clause.')
CHOICES = {'operator':('ANY','ALL'), 'requirement':('symptoms_suffice','also_require_separate_diagnosis'),
           'target':('screened_patient_current_presentation',),
           'population_evidence':('explicit_female_or_woman_patient_description',),
           'additional_thresholds':('none',)}
TERMS = {
    'dysmenorrhea': ['dysmenorrhea','painful menstruation','severe premenstrual and menstrual pelvic pain'],
    'dyspareunia': ['dyspareunia','pain during intercourse'],
    'chronic_pelvic_pain': ['chronic pelvic pain'],
    'menorrhagia': ['menorrhagia','heavy menstrual periods','heavy, irregular periods'],
    'metrorrhagia': ['metrorrhagia','bleeding between periods','occasional spotting between periods'],
}
OWNER_RE = re.compile(r'^(?:[Aa] (?:[0-9]+[ -]year[ -]old )?(?P<population>woman|female)|The patient|She) '
                      r'(?P<verb>complains of|reports|denies) (?P<listing>.+?)\.$', re.I)
ALIASES = {term: key for key, terms in TERMS.items() for term in terms}
ATOM = '(?:'+'|'.join(re.escape(t) for t in sorted(ALIASES,key=len,reverse=True))+')'
SEP = r'(?:, (?:and )?| and )'
LIST = re.compile(ATOM+'(?:'+SEP+ATOM+')*',re.I)
ATOM_MATCH = re.compile(ATOM,re.I)

def canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()

def packet():
    if sha256(REGISTRY.read_bytes()).hexdigest()!=DIGEST:
        raise ValueError('Registry snapshot mismatch')
    return dict(study=STUDY,criterion_id=CASE,registry_sha256=DIGEST,
                criterion_text=SOURCE['criterion_text'],question=QUESTION,
                governing_protocol_sha256=None,governing_version=None,source_locator=None,
                response_fields={key:list(values)+['other_requires_followup'] for key,values in CHOICES.items()},
                answer=None)

def verify_answer(envelope, trust, protocol_bytes, as_of):
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    p = envelope['payload']
    if set(p) != {'study','criterion_id','registry_sha256','question_sha256','governing_protocol_sha256',
                  'governing_version','source_locator','authority_id','decision_id','decision_date','interpretation'}:
        raise ValueError('Incomplete or unsupported answer')
    if not isinstance(as_of,date): raise ValueError('Supply the screening date')
    decision_date=date.fromisoformat(p['decision_date'])
    if (p['study'],p['criterion_id'],p['registry_sha256'],p['question_sha256']) != (STUDY,CASE,DIGEST,fingerprint(packet())):
        raise ValueError('Scope or question mismatch')
    if not protocol_bytes or sha256(protocol_bytes).hexdigest()!=p['governing_protocol_sha256']:
        raise ValueError('Protocol bytes mismatch')
    # This configuration is provisioned out of band. The answer never supplies its own verification key.
    owner=trust['authorities'][p['authority_id']]
    if [STUDY,CASE,p['governing_version'],p['governing_protocol_sha256']] not in owner['scope']:
        raise ValueError('Untrusted protocol version or reviewer')
    if (not owner['active'] or not date.fromisoformat(owner['valid_from'])<=decision_date<=as_of<=date.fromisoformat(owner['valid_until'])
            or p['decision_id'] in trust['revoked'] or p['decision_id']!=owner['active_decision_id']
            or not all(isinstance(p[k],str) and p[k].strip() for k in ('decision_id','governing_version','source_locator'))):
        raise ValueError('Decision revoked, stale or lacking attribution')
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(owner['public_key'],validate=True)).verify(
            base64.b64decode(envelope['signature'],validate=True),canonical(p))
    except InvalidSignature as e:
        raise ValueError('Invalid reviewer signature') from e
    spec=p['interpretation']
    if not isinstance(spec,dict) or set(spec)!=set(CHOICES) or any(spec[k] not in v for k,v in CHOICES.items()):
        raise ValueError('Unmodelled interpretation; protocol follow-up required')
    return p

def reviewed_rule(spec):
    required = [{'fact':'female_description'},
                {spec['operator'].lower():[{'fact':s} for s in SYMPTOMS]}]
    keys=['female_description',*SYMPTOMS]
    if spec['requirement']=='also_require_separate_diagnosis':
        required.append({'fact':'pelvic_congestion_diagnosed'})
        keys.append('pelvic_congestion_diagnosed')
    rule=dict(facts={k:fact(k,scope='Current screened patient presentation: '+k.replace('_',' ')) for k in keys},expression={'all':required})
    validate(rule)
    return rule

class CurrentComplaints:
    """Bounded, current-patient assertions from a verified single-document FHIR bundle."""
    def __init__(self,bundle,patient):
        subject='Patient/'+patient
        rs=[e['resource'] for e in bundle['entry']]
        view=NativeChart(rs,subject,{},STUDY)
        documents=[r for r in rs if r.get('resourceType')=='DocumentReference']
        if (len(documents)!=1 or [r.get('id') for r in rs if r.get('resourceType')=='Patient']!=[patient]
                or any(r.get('resourceType')=='Group' or r.get('subject',{}).get('reference',subject)!=subject for r in rs)):
            raise ValueError('Expected one patient and one source note')
        body=base64.b64decode(documents[0]['content'][0]['attachment']['data'],validate=True).decode()
        self.facts=defaultdict(list)
        self.spans={}
        self.ambiguous=set()
        self.digest=view.hash
        offset=0
        current_section = True
        patient_context = True
        pronoun_subject = False
        current_headers={'presenting complaint','current symptoms','history of present illness','chief complaint','hpi'}
        excluded_headers=('family history','family medical history','past medical history','past history','previous history',
                          'past psychiatric history','surgical history','social history','past surgical history',
                          'historical symptoms','previous symptoms','prior symptoms','past symptoms','pmh','fh','fhx','psh')
        if any(r.get('resourceType')=='Patient' and r.get('id')==patient
               and r.get('gender') not in (None,'unknown','female') for r in rs):
            self.ambiguous.add('female_description')
        for line_num,raw in enumerate(body.splitlines(keepends=True)):
            line=re.sub(r'^\s*\d+\.\s+', '', raw.rstrip('\r\n')).strip()
            begin=offset+raw.index(line) if line else offset
            offset+=len(raw)
            line_subject = line.lower()
            if not line:
                pronoun_subject=False
                continue
            if (current_section and re.fullmatch(r'(?:sex|gender):\s*(?:male|man|boy)\.?',line,re.I)):
                self.ambiguous.add('female_description')
            # A section keeps its context on subsequent lines, including lines with an explicit subject.
            header=re.fullmatch(r'([A-Za-z][A-Za-z /-]{0,50}):(?:\s*(.*))?',line)
            if current_section and header and header[1].casefold() in {'correction','addendum','amendment'}:
                for term in ATOM_MATCH.finditer(line):
                    self.ambiguous.add(ALIASES[term[0].lower()])
                if re.search(r'\b(?:female|woman|male|man|sex|gender)\b',line_subject):
                    self.ambiguous.add('female_description')
                if 'pelvic congestion' in line_subject:
                    self.ambiguous.add('pelvic_congestion_diagnosed')
                pronoun_subject=False
                continue
            if header or line_subject in current_headers or any(
                    re.match(re.escape(h)+r'(?:\b|$)',line_subject) for h in excluded_headers):
                title=header[1].lower() if header else line_subject
                current_section=title in current_headers
                patient_context=current_section
                pronoun_subject=False
                if not (current_section and header and header[2]):
                    continue
                begin+=header.start(2)
                line=header[2]
                line_subject=line.lower()
            if not current_section:
                continue
            relative=re.search(r"\b(?:family|mother|father|sister|brother|guardian|caregiver|daughter|son|spouse|partner|wife|husband|aunt|uncle|maternal|paternal|another patient)\b",line_subject)
            historical=re.search(r"\b(?:previously|historically|in the past|prior visit|last (?:year|month|week)|(?:years?|months?|weeks?) ago)\b",line_subject)
            if relative or historical:
                patient_context=False
                pronoun_subject=False
                continue
            explicit_patient=line_subject.startswith('the patient ')
            if explicit_patient:
                patient_context=True
            if not patient_context or (line_subject.startswith('she ') and not pronoun_subject):
                continue
            conflict=re.search(r"^(?:the patient (?:is|was|identifies as|is recorded as)|a (?:[0-9]+[ -]year[ -]old )?)(?: (?:a|an))?\s*(?:male|man|boy)\b|^the patient is not (?:a woman|female)\b",line_subject)
            if conflict:
                self.ambiguous.add('female_description')
            def put(key,value,a,b):
                ref=f'{view.source}#sha256={view.hash}&line={line_num}&start={begin+a}&end={begin+b}'
                self.spans[ref]=dict(document=view.source,line=line_num,start=begin+a,end=begin+b,quote=body[begin+a:begin+b])
                self.facts[key].append((value,ref))
            m=OWNER_RE.fullmatch(line)
            recognized = bool(m and LIST.fullmatch(m['listing']))
            if recognized:
                if m['population']: put('female_description',True,*m.span('population'))
                for term in ATOM_MATCH.finditer(m['listing']):
                    put(ALIASES[term[0].lower()],m['verb'].lower()!='denies',m.start('listing')+term.start(),m.start('listing')+term.end())
            else:
                for term in ATOM_MATCH.finditer(line):
                    self.ambiguous.add(ALIASES[term[0].lower()])
            if line.lower() in ('the patient is a woman.','the patient is female.'):
                put('female_description',True,0,len(line))
            if line.lower() in ('the patient has a confirmed diagnosis of pelvic congestion.',
                                'the patient does not have pelvic congestion.'):
                put('pelvic_congestion_diagnosed','confirmed diagnosis' in line.lower(),0,len(line))
            elif 'pelvic congestion' in line.lower():
                self.ambiguous.add('pelvic_congestion_diagnosed')
            # Retain a pronoun only across contiguous, unambiguous patient assertions.
            pronoun_subject = recognized or line_subject in ('the patient is a woman.','the patient is female.')
    def read(self,spec):
        values=self.facts[spec['label']]
        refs=[ref for _,ref in values]
        if spec['label'] in self.ambiguous or len({v for v,_ in values})!=1:
            return None,'MISSING_DATA',refs,'Confirm current '+spec['scope']+'.'
        return values[0][0],None,refs,spec['scope']

def apply(bundle,patient,envelope,trust,protocol_bytes,as_of,queue=None):
    # Compatibility entry point: decisions always come from the ordinary FHIR matcher.
    if __package__:
        from .release import screen_reviewed
    else:
        sys.path.insert(0,str(HERE.parent))
        from review706.release import screen_reviewed
    resources=[item['resource'] for item in bundle['entry']]
    result=screen_reviewed(resources,'Patient/'+patient,read_json(BENCH/'round11/compiled.json'),
                           STUDY,CASE,envelope=envelope,trust=trust,protocol_bytes=protocol_bytes,as_of=as_of)
    trace=dict(result['criteria'][CASE],source_sha256=result['source_sha256'])
    if envelope is None:
        return dict(trace,question=QUESTION)
    decision=result['protocol_decision']
    if queue is not None:
        scope={'study':STUDY,'criterion_id':CASE,'protocol_sha256':decision['governing_protocol_sha256']}
        q=queue.register(scope,{**scope,'clinical_questions':[{'question':QUESTION}]})[0]
        queue.answer(q['id'],canonical(envelope['payload']['interpretation']).decode(),decision['authority_id'],
                     decision['decision_date'],decision['source_locator'])
    trace.update({k:decision[k] for k in ('rule_sha256','signed_answer_sha256','registry_sha256',
                                         'decision_id','governing_protocol_sha256')})
    return trace

def frozen_bundle():
    raw=read_json(BENCH/'round9/notes.json')[PATIENT]
    pinned=read_json(BENCH/'round9/note_hashes.json')[PATIENT]
    if sha256(raw.encode()).hexdigest()!=pinned: raise ValueError('Changed benchmark note')
    return benchmark_chart(PATIENT,raw,'2026-01-01T00:00:00Z')[0]

if __name__=='__main__':
    opts=argparse.ArgumentParser(description=__doc__)
    opts.add_argument('--answer',type=Path);opts.add_argument('--trust',type=Path)
    opts.add_argument('--governing-protocol',type=Path);opts.add_argument('--as-of',type=date.fromisoformat)
    opts.add_argument('--review-db',type=Path)
    args=opts.parse_args()
    if args.answer:
        if not (args.trust and args.governing_protocol and args.as_of): opts.error('Supply independent trust configuration, governing protocol bytes and as-of date.')
        print(json.dumps(apply(frozen_bundle(),PATIENT,read_json(args.answer),read_json(args.trust),args.governing_protocol.read_bytes(),
                               args.as_of,ReviewQueue(args.review_db) if args.review_db else None),indent=2))
    else:
        print(json.dumps(packet(),indent=2))
