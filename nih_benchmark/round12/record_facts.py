"""Reusable note-to-chart readers for explicit medications, diagnoses and measured values."""
import json
import re
from pathlib import Path
from prose import Finding, UNCERTAIN, parts

ROOT=Path(__file__).resolve().parent.parent/'round9'
RX=json.loads((ROOT/'rxnorm.json').read_text())
ICD=json.loads((ROOT/'icd10cm.json').read_text())
DIAG={k.replace('-',' '):k for k in ICD}
DIAG.update({'diabetes':'diabetes-mellitus','diabetes mellitus':'diabetes-mellitus','hypertension':'hypertension',
             'bipolar disorder':'bipolar-disorder','allergic rhinitis':'allergic-rhinitis','hypercholesterolemia':'hypercholesterolemia',
             'spinal stenosis':'spinal-stenosis','dementia':'dementia','tuberculosis':'tuberculosis',
             'renal artery stenosis':'renal-artery-stenosis','type 2 diabetes':'type-2-diabetes',
             'iron deficiency':'iron-deficiency','obesity':'obesity','hypothyroidism':'hypothyroidism'})
NUM=r'(\d+(?:\.\d+)?)'
UNITS={'heart_rate':'/min','respiratory_rate':'/min','gcs':'1','age-at-presentation':'a','serum_creatinine_mg_dl':'mg/dL'}
VITAL_PATTERNS={
 'heart_rate':r'(?:heart rate|pulse|hr)(?:\s+(?:is|was|of|is irregular at))?\s*:?\s*'+NUM+r'\s*(?:beats?\s*(?:/|per)\s*min(?:ute)?|bpm|/min)\b',
 'respiratory_rate':r'(?:respiratory rate|respirations|rr)(?:\s+(?:is|are|was|were|of))?\s*:?\s*'+NUM+r'\s*(?:breaths?\s*(?:/|per)\s*min(?:ute)?|bpm|/min)\b',
 'serum_creatinine_mg_dl':r'serum creatinine(?:\s+(?:is|was|of))?\s*:?\s*'+NUM+r'\s*mg/dl\b',
 'gcs':r'(?:glasgow coma scale(?: \(gcs\))?|gcs)(?:\s+(?:is|was|of))?\s*:?\s*'+NUM+r'\s*/\s*15\b',
}
def facts(text,section,study):
    t=' '.join(text.lower().replace('’',"'").split()).rstrip('.')
    if section in {'plan','family history','obstetric history','assessment and plan','history'} or UNCERTAIN.search(t):return []
    family=re.search(r'\b(?:mother|father|sister|brother|wife|husband|family|daughter|son|partner)\b',t)
    if family:return []
    out=[]
    # Narrow present-examination grammar. Keep a qualitative sign separate
    # from the numeric quantity, which requires a measured value and unit.
    examination = re.fullmatch(
        r"(?:on (?:physical )?examination,? )?(?:he|she|the patient) is (.+)", t)
    if examination and section != 'past medical history':
        terms = re.split(r",? as well as |, and | and |, ", examination[1])
        signs = {"tachycardic": "tachycardia", "tachypneic": "tachypnea"}
        allowed = set(signs) | {"pale", "in moderate discomfort"}
        if all(term in allowed for term in terms):
            for term in terms:
                if term in signs:
                    out.append(Finding("exam-sign-" + signs[term], True))
    age=re.match(r'^(?:a |an )?(\d{1,3})[- ](?:(year|month|day)[- ]old|yo)\s+(?:(?:white|black|caucasian|african-american|obese|generally healthy|nonsmoker) )*(?:man|woman|male|female|girl|boy|infant|child)\b',t)
    if age and section not in {'history','past medical history'}:
        unit = {"month": "mo", "day": "d"}.get(age[2], "a")
        out.append(Finding('quantity:age-at-presentation',int(age[1]),quantity_unit=unit))
    med=re.fullmatch(r'(?:(?:his|her|the patient.s) current medications (?:are|include)|(?:she|he|his|the patient) (?:currently takes|is currently taking|already receives|currently receives|continues to take)) (.+)',t)
    if not med:
        med=re.fullmatch(r'(?:she|he|the patient) is on (?:[a-z-]+ )?medications, including (.+)',t)
    if med and section!='past medical history':
        for token in parts(med[1]):
            term='iron supplement' if token=='iron supplementation' else token
            if term in RX or term=='iron supplement':out.append(Finding('medication:'+term,'active'))
    history=re.fullmatch(r'(?:(?:he|she|the patient) (?:has a (?:past )?medical history of|has a history of)|(?:his|her) past medical history is notable for) (.+)',t)
    current=re.fullmatch(r'(?:he|she|the patient) (?:is known to have|has a confirmed diagnosis of|carries a diagnosis of) (.+)',t)
    if history or current:
        for token in parts((history or current)[1]):
            if token in DIAG:out.append(Finding('condition:'+DIAG[token],'history' if history else 'documented'))
    if section=='past medical history':return [f for f in out if f.value=='history']
    # Vital measurements require an examination or a current measurement clause, an
    # explicit unit and an unambiguous subject. Never assign a rate to an adjective.
    if re.search(r'\b(?:reference|range|target|goal|between|estimated|denies|not|prior|previous|baseline|history|threshold|at least|less than|over|below|above|greater than|up to)\b|[<>≤≥~?]',t):return out
    exam=re.match(r"^(?:on (?:physical )?examination|on exam|upon arrival|physical exam|exam|vital(?:s| signs)?|bp\b|blood pressure\b|his |her |the patient.s |heart rate\b|hr\b|rr\b|pulse\b|respiratory rate\b|serum creatinine\b|(?:the )?glasgow coma scale\b|gcs\b)",t) or section in {'vitals','physical examination','examination'}
    if exam:
        for key,pat in VITAL_PATTERNS.items():
            for match in re.finditer(r'\b'+pat,t):
                if re.match(r'\s*(?:-|–|to\b|or\b|and then\b|before\b|after\b)',t[match.end():]):continue
                if key=='serum_creatinine_mg_dl':
                    # Only a complete patient measurement phrase may supply this
                    # concentration. A trailing qualification can change its meaning.
                    if match.end()!=len(t) or (match.start()!=0 and not re.search(
                            r"(?:^|, (?:and )?)(?:his |her |the patient's |upon arrival,? )$",t[:match.start()])):
                        continue
                val=float(match[1])
                if key=='gcs' and (not 3<=val<=15 or not val.is_integer()):continue
                out.append(Finding('quantity:'+key,int(val) if val.is_integer() else val))
    return out

# Document the polarity and temporal scope of observed findings separately. An
# unqualified symptom never supplies a diagnosis, laboratory result or score.
SYMPTOMS={'fever':'fever','cough':'cough','rash':'rash','diarrhea':'diarrhea','trauma':'trauma',
          'smoking':'smoking','difficulty sleeping':'difficulty-sleeping','upper respiratory tract symptoms':'upper-respiratory-symptoms',
          'hypercholesterolemia':'hypercholesterolemia','diabetes':'diabetes-mellitus','headache':'headache',
          'night terrors':'night-terrors','wheezing':'wheezing','tachycardic':'tachycardia','tachypneic':'tachypnea'}
def symptoms(text,section):
    t=' '.join(text.lower().split()).rstrip('.')
    if section in {'plan','family history','obstetric history','assessment and plan','history','past medical history'} or UNCERTAIN.search(t):return []
    # A change of experiencer terminates the patient's coordinated symptom list.
    m=re.match(r'^(?:he|she|the patient) (denies|reports|has had no) (.+)$',t)
    if m:
        phrase=re.split(r'(?:,? (?:or |and )?a family history of |,? (?:but |and )?(?:his|her|their) (?:mother|father|sister|brother))',m[2])[0]
        # End a list before a change of predicate so a negation cannot cross it.
        phrase=re.split(r'\s+(?:and|but)\s+(?:reports|denies|sleeps|has|developed|now has)\b',phrase)[0]
        tokens=parts(phrase.rstrip(','))
        if not all(v in SYMPTOMS for v in tokens):return []
        prefix='recent-symptom:' if m[1]=='has had no' else 'symptom:'
        return [Finding(prefix+SYMPTOMS[v],m[1]=='reports') for v in tokens]
    m=re.fullmatch(r'no history of (.+)',t)
    if m:return [Finding('prior-symptom:'+SYMPTOMS[v],False) for v in parts(m[1]) if v in SYMPTOMS]
    return []
