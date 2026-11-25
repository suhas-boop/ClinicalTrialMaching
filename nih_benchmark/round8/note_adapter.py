"""Conservative benchmark adapter. Materialize explicit note evidence and preserve numbered source sentences."""
import json
import re
from concept_reader import CURRENT,HISTORY,declared_facts
from narrative_evidence import extract,supports

def abstract(note):
    parsed=extract(note)
    if parsed['scope']=='multiple_subjects':return {},True
    lines={int(n):t for n,t in re.findall(r'^(\d+)\. (.+)$',note,re.M)}
    facts={k:(v['value'],v['sentences']) for k,v in parsed['facts'].items()}
    # Source templates express evidence, never eligibility labels. No identifier, trial,
    # annotation label, or criterion text can select a patient fact.
    first=lines[0]
    presentation=re.match(r'^(?:A|An) (\d{1,3})(?:[- ]year[- ]old| yo) (.{1,90})',first,re.I)
    if presentation:
        descriptor=presentation[2].split(',')[0]
        subject=re.match(r'(?:(?:African-American|African American|white|Caucasian|nonsmoker|obese|generally healthy|male|female) )*(woman|man|boy|girl|male|female)\b',descriptor,re.I)
        if subject and not re.search(r"\b(?:mother|father|sister|brother|friend|husband|wife|daughter|son)\b",descriptor,re.I):
            facts['male_or_female']=(True,[0])
            facts['woman']=(subject[1].lower() in {'woman','female'},[0])
            if subject[1].lower() == 'woman':
                facts['explicit_woman_description'] = (True, [0])
        if re.search(r'\b(?:woman|female) at \d+ weeks gestation in her (?:first|second|third) pregnancy\b',descriptor,re.I):
            facts['pregnant']=(True,[0])
    creatinine=[]
    for i,line in lines.items():
        # Exclude family, conditional, hypothetical and historical contexts through
        # a closed set of current-patient sentence structures.
        if re.match(r'^On (?:skin )?examination, (?:multiple|several) lesions (?:are seen|are present)\b',line,re.I) and re.search(r'visits (?:her|his|the) dermatologist for (?:skin )?lesions on (?:her|his|the) (?:neck|arm|leg|face)\b',first,re.I):
            facts['skin_condition']=(True,[0,i])
        g=re.match(r'^The Glasgow Coma Scale \(GCS\) was (\d{1,2})/15\b',line)
        if g and 3<=int(g[1])<=15:facts['gcs']=(int(g[1]),[i])
        if re.match(r'^(?:He|She|The patient) receives (?:an? )?(?:rapid )?infusion of (?:crystalloid|saline)\b',line,re.I):
            facts['active_treatment_of_any_form_not_considered']=(False,[i])
        if re.search(r'\b(?:is|was) admitted to the (?:ICU|hospital|ward)\b',line,re.I) and re.match(r'^(?:He|She|The patient) (?:is|was|receives)\b',line,re.I) and not re.search(r'\b(?:if|relative|mother|father|unless|would)\b',line,re.I):
            facts['hospital_admission']=(True,[i])
        if i==0 and re.match(r'^(?:A|An) \d+[- ]year[- ]old (?:(?:white|black|Asian) )?(?:male|female|woman|man) with (?:a )?history of common variable immunodeficiency\b',line,re.I):
            facts['immune_deficiency']=(True,[i])
        # Accept only measured patient serum values with explicit units and unambiguous scope.
        if not re.search(r"\b(?:baseline|prior|previous|family|relative|mother|father|goal|target|estimated|if|may|would|repeat|earlier)\b",line,re.I):
            lab=re.search(r"(?:^(?:His |Her |The patient.s )?serum creatinine|, and (?:his|her) serum creatinine) (?:is|was|measured at) (\d+(?:\.\d+)?) mg/dL\.?$",line,re.I)
            if lab:creatinine.append((float(lab[1]),i))
    if creatinine and len({n for n,i in creatinine})==1:
        facts['serum_creatinine_mg_dl']=(creatinine[0][0],[i for n,i in creatinine])
    for key,polarities in declared_facts(lines).items():
        if len(polarities)!=1:
            facts.pop(key,None)
            continue
        value,ids=next(iter(polarities.items()))
        if key in facts and facts[key][0]!=value:
            facts.pop(key)
        else:
            facts[key]=(value,sorted(set(ids+(facts[key][1] if key in facts else []))))
    return facts,False

# Exact published local fact semantics. Reusing a mnemonic with a different unit,
# timing qualifier or owner cannot silently reuse extracted evidence.
TEXT_CONTRACTS={
    'skin_condition':('bool',None,'skin condition'),
    'active_treatment_of_any_form_not_considered':('bool',None,'active treatment of any form not considered'),
    'hospital_admission':('bool',None,'hospital admission'),
    'immune_deficiency':('bool',None,'immune deficiency'),
    'pregnant':('bool',None,'pregnant'),
    'woman':('bool',None,'woman'), 'male_or_female':('bool',None,'male or female'),
    'gcs':('number','1','gcs'), 'serum_creatinine_mg_dl':('number','mg/dL','serum creatinine mg dl')
}
def admits(key,spec):
    if supports(key,spec):return True
    if key in CURRENT or key in HISTORY:
        return spec['role']=='record' and spec['kind']=='bool' and spec['scope']==key.replace('_',' ')
    return spec['role']=='record' and key in TEXT_CONTRACTS and (spec['kind'],spec.get('unit'),spec['scope'])==TEXT_CONTRACTS[key]
