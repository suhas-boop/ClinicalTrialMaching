"""Extract assertions from single-patient prose. Longitudinal inference is deliberately bounded."""
from dataclasses import dataclass
import re
from clinical_fields import FIELDS, SKIN, MARITAL, STUDY_SECTIONS, allowed_number
from concept_reader import CURRENT, HISTORY

BY_FACT={}
for field in FIELDS:
    for fact in field.facts: BY_FACT.setdefault(fact,field)
@dataclass(frozen=True)
class Finding:
    key:str
    value:object
    field:object=None
    study:str|None=None
    quantity_unit:str|None=None

def finding(key,val,study=None):
    f=BY_FACT.get(key)
    if f and f.section in STUDY_SECTIONS and not study:return None
    return Finding(key,val,f,study)

# Shared aliases for explicit, current observations. Relation and polarity are
# parsed independently; an alias on its own does not establish a patient fact.
ALIASES={
 'has_social_insurance':('covered by social insurance','enrolled in social insurance'),
 'on_artificial_ventilation':('on artificial ventilation','receiving artificial ventilation'),
 'bulk_symptoms':('pelvic bulk symptoms',),
 'family_history_of_bleeding':('a family history of bleeding',),
 'failed_mri_metal_screen':('failed the mri metal safety screen',),
 'adequate_contraception':('using contraception judged adequate for this study',),
 'childbearing_potential':('of childbearing potential',),
 'prior_azole_or_echinocandin_allergy_hypersensitivity_or_serious_reaction':('a documented allergy to an azole antifungal','a documented allergy to an echinocandin'),
 'early_bone_marrow_failure_in_childhood':('a documented history of early childhood bone marrow failure',),
 'recurrent_hematoma':('a recurrence of the index hematoma',),
 'child_involved_in_motor_vehicle_collision_at_index_injury':('involved in a motor vehicle collision at the index injury',),
 'breastfeeding':('breastfeeding','breast-feeding','nursing her infant','nursing her baby','breastfeed her baby','breastfeed her infant'),
 'hemodynamically_unstable':('hemodynamically unstable','haemodynamically unstable'),
 'receiving_mechanical_ventilation':('on a mechanical ventilator','mechanically ventilated','receiving mechanical ventilation','on mechanical ventilation'),
 'systemic_anticoagulation':('systemically anticoagulated','receiving systemic anticoagulation'),
 'can_take_oral_medication':('able to take pills by mouth','able to take oral medication','taking pills by mouth','tolerating oral medications'),
 'can_retain_oral_medication':('able to keep tablets down','able to keep oral medications down'),
 'patient_reported_hematuria':('gross hematuria','visible blood in the urine','blood in my urine'),
 'postmenopausal_woman':('postmenopausal','post-menopausal'),
 'undergoing_emergency_laparotomy':('undergoing emergency laparotomy','undergoing emergent laparotomy'),
 'transferred_to_observation_unit':('transferred to the observation unit','transferred to observation status'),
 'sedation_required_to_hold_still':('in need of sedation to remain still','unable to remain still without sedation'),
 'refused_written_consent':('declined written informed consent','refused written informed consent'),
 'consent_refused':('declined consent','refused consent'),
 'unable_to_provide_written_consent':('unable to give written informed consent','unable to provide written informed consent'),
 'unable_to_speak_french':('unable to speak french',),
 'unable_to_speak_english':('unable to speak english',),
 'unable_to_travel_for_treatment_or_followup':('unable to travel to the site for treatment or follow-up','cannot travel to the site for treatment or follow-up'),
 'unmarried':('divorced','widowed','never married','married'),
}
INVERSE={'breathing spontaneously without mechanical ventilation':('receiving_mechanical_ventilation',False),
         'hemodynamically stable':('hemodynamically_unstable',False)}
WORDS={alias:k for k,aliases in ALIASES.items() for alias in aliases}
for k,aliases in CURRENT.items():
    for alias in aliases.split('|'):WORDS.setdefault(alias,k)
# Current neurological examination, vital signs and symptoms are separate from
# diagnoses or an investigator's assessment of eligibility.
HIST={alias:k for k,v in HISTORY.items() for alias in v.split('|')}
REPORTS={
 'head ct':{'ich':'ct_intracranial_hemorrhage','intracranial hemorrhage':'ct_intracranial_hemorrhage','intracranial haemorrhage':'ct_intracranial_hemorrhage',
            'cerebral edema':'ct_cerebral_edema','edema':'ct_cerebral_edema','diffuse axonal injury':'ct_diffuse_axonal_injury'},
 'chest ct':{'pe':'chest_ct_showed_pulmonary_thromboembolism','pulmonary embolism':'chest_ct_showed_pulmonary_thromboembolism','pulmonary thromboembolism':'chest_ct_showed_pulmonary_thromboembolism',
             'interstitial lung disease':'chest_ct_showed_ild','lung cancer':'chest_ct_showed_lung_cancer','active pulmonary tuberculosis':'chest_ct_showed_active_tb'},
 'ecg':{'acute ischemia':'ecg_acute_ischemia','signs of acute ischemia':'ecg_acute_ischemia'},
}
SECTIONS={'social history','respiratory support','dermatology','birth history','hospital course','examination','assessment','vitals','physical examination','current head ct','current chest ct','current ecg','imaging','history','family history','plan','obstetric history','past medical history','assessment and plan'}
BLOCK={'history','family history','plan','obstetric history','past medical history','assessment and plan'}
UNCERTAIN=re.compile(r"\b(?:possible|possibly|suspected|suspect|equivocal|questionable|may|might|could|cannot exclude|cannot rule out|not excluded|if|pending|planned|recommended|tomorrow|previously|last (?:week|year|month)|years? ago|yesterday)\b|\?",re.I)
def parts(text):
    return [s.strip() for s in re.split(r',\s*(?:(?:and|or)\s+)?|\s+(?:and|or)\s+',text) if s.strip()]

def report(text,study):
    m=re.fullmatch(r'(?:the )?(?:current |today.s )?(head ct|ct head|chest ct|ct chest|ecg|ekg)(?: today)? (?:shows?|showed|demonstrates?|demonstrated|reveals?|revealed|is|was) (.+)',text)
    if not m:return []
    modality={'ct head':'head ct','ct chest':'chest ct','ekg':'ecg'}.get(m[1],m[1])
    if modality=='head ct' and m[2] in ('normal','unremarkable','abnormal'):
        return [finding('normal_head_ct',m[2]!='abnormal',study)]
    out=[]
    for segment in re.split(r'\s+but\s+(?:shows? |demonstrated |demonstrates? )?|(?=\s+without\s+)',m[2]):
        segment=segment.strip()
        prefix=re.match(r'(no evidence of |no |without |negative for )',segment)
        values=parts(segment[prefix.end():] if prefix else segment)
        if not values or any(v not in REPORTS[modality] for v in values):return []
        out.extend(finding(REPORTS[modality][v],not prefix,study) for v in values)
    return out

def consent_findings(text, study):
    """Separate current disposition from intent, and retain the declared study."""
    intent = re.fullmatch(
        r"(?:the patient|he|she) will (?:give|provide) (?:written )?informed consent"
        r"(?:,? and will comply with the trial protocol without any practical issues)?", text)
    if intent:
        return [Finding("expressed-future-consent-intent", True, study=study)]
    if not study:
        return []
    # These templates describe the patient's own current screening disposition.
    # A consent from another visit or an unspecified study is insufficient.
    match = re.fullmatch(
        r"(?:at screening,? )?(?:the patient|he|she) "
        r"(gave written informed consent|declined written informed consent|"
        r"refused written informed consent) at (?:this|the current) screening visit", text)
    if not match:
        return []
    refused = match[1] != "gave written informed consent"
    findings = [finding(key, refused, study)
                for key in ("refused_written_consent", "consent_refused")]
    if not refused:
        findings.append(finding("consent_absent", False, study))
    return findings

def interpret(text,section,study):
    t=' '.join(text.lower().replace('’',"'").split()).rstrip('.')
    if not t or section in BLOCK or UNCERTAIN.search(t):return []
    consent = consent_findings(t, study)
    if consent:
        return consent
    if section in {'current head ct','current chest ct','current ecg'}:
        findings=report(section+' showed '+t,study)
        if findings:return findings
    fronted=re.fullmatch(r'on (?:today.s|the current) (head ct|chest ct|ecg) there (?:is|are) (.+)',t)
    if fronted:
        result=fronted[2].replace('no sign of ','no ').replace('a pulmonary embolus','pulmonary embolism')
        return report('current '+fronted[1]+' showed '+result,study)
    inverse_report=re.fullmatch(r'(no .+?) on (?:today.s|the current) (head ct|chest ct|ecg)',t)
    if inverse_report:
        return report('current '+inverse_report[2]+' showed '+inverse_report[1],study)
    observations=report(t,study)
    if observations:return observations
    nums=[
        ('paco2_mmhg',r'(?:the )?(?:abg|arterial blood gas)(?: today)?(?: showed| shows|:)? (?:a )?(?:paco2|pco2)(?: of|:| was)? (\d+(?:\.\d+)?)\s*mm\s*hg'),
        ('paco2_mmhg',r'(?:paco2|pco2) on arterial sampling (?:is|was) (\d+(?:\.\d+)?)\s*mm\s*hg'),
        ('gcs_motor',r'(?:gcs|glasgow coma scale) motor (?:subscore|score)(?::| was| is)?\s*(\d+)\s*/\s*6'),
        ('gestation_at_birth_weeks',r'(?:the (?:patient|infant|child) was born at|born at) (\d+(?:\.\d+)?) weeks(?:\x27 gestation| of gestation)?'),
        ('who_performance_status',r'who performance (?:status|score)(?: is| was|:| of)?\s*(\d+)'),
    ]
    if section=='birth history':nums.append(('gestation_at_birth_weeks',r'delivered at (\d+(?:\.\d+)?) weeks(?:\x27 gestation| of gestation)?'))
    for key,pat in nums:
        m=re.fullmatch(pat,t)
        if m and allowed_number(float(m[1]),BY_FACT[key]):return [finding(key,float(m[1]))]
    m=re.fullmatch(r'(?:(?:skin exam(?:ination)? documented )?fitzpatrick (?:phototype|type)|skin phototype (?:was|is) fitzpatrick|fitzpatrick (?:skin )?(?:type|phototype)) ([iv]+)',t)
    if m and m[1].upper() in ('I','II','III','IV','V','VI'):return [Finding('skin phototype',m[1].upper(),SKIN)]
    # A family history assertion is accepted only for the relevant family-history fact.
    m=re.fullmatch(r'(no )?family history of bleeding(?: was reported| was documented)?',t)
    if m:return [finding('family_history_of_bleeding',not m[1])]
    m=re.fullmatch(r'(?:the )?admission cognitive screen(?:ing)? (?:found|documented|showed) (impairment|no impairment|normal cognition)',t)
    if m:return [finding('cognitive_impairment_on_admission_screen',m[1]=='impairment')]
    m=re.fullmatch(r'(?:the )?mri (?:metal )?safety screen(?:ing)? (?:was |is )?(passed|failed) because of metal',t)
    if m:return [finding('failed_mri_metal_screen',m[1]=='failed')]
    m=re.fullmatch(r'(?:a |the )?neurologic(?:al)? examination (?:is|was) (unremarkable|normal|abnormal)(?:, but .+)?',t)
    if m:return [Finding('abnormal_neurologic_exam',m[1]=='abnormal')]
    m=re.fullmatch(r'(?:he|she|the patient) (?:has|reports|denies) (?:a |any )?history of (.+)',t)
    if m and m[1] in HIST:return [finding(HIST[m[1]],'denies ' not in t)]
    # Identify the subject before assigning polarity. Bare fragments are accepted
    # only in current-patient sections or for a narrowly scoped status statement.
    t=re.sub(r'^in (?:the recovery bay|the icu|recovery),? ','',t)
    subject=re.match(r'^(?:the patient|patient|he|she)\s+',t)
    if subject:t=t[subject.end():]
    elif section not in {'hospital course','examination','physical examination','respiratory support','assessment','social history'}:return []
    stance=re.match(r'^(?:currently |now )?(?:denies(?: any)? |has no |does not have |is not |continues to |has |reports |is |remains )',t)
    negative=False
    if stance:
        negative=bool(re.search(r'\b(?:denies|no|not)\b',stance[0]))
        t=t[stance.end():]
    t=re.sub(r'^(?:currently|now) ','',t)
    if t in INVERSE:
        key,val=INVERSE[t];return [finding(key,val)] if not negative else []
    if t=='taking pills by mouth and keeping them down':
        return [] if negative else [finding('can_take_oral_medication',True),finding('can_retain_oral_medication',True)]
    if t in WORDS:
        key=WORDS[t]
        if key=='prior_azole_or_echinocandin_allergy_hypersensitivity_or_serious_reaction' and negative:return []
        if key=='unmarried':return [] if negative else [Finding(key,t,MARITAL)]
        if key=='patient_reported_hematuria' and (not subject or not stance or not re.search('reports|denies',stance[0])):return []
        hit=finding(key,not negative,study)
        return [hit] if hit else []
    return []

def segments(raw, *, allowed_sections=SECTIONS):
    """Yield findings with byte-independent Unicode offsets into the exact original note."""
    section='';offset=0;relative=False
    for i,line in enumerate(raw.splitlines(keepends=True)):
        whole=line.rstrip('\r\n')
        prefix=re.match(r'^\s*(?:\d+\.\s+)?',whole)
        start=prefix.end();body=whole[start:]
        heading=re.match(r'^([\w /-]{2,40}):\s*',body)
        if heading and heading[1].lower() in allowed_sections:
            section=heading[1].lower();relative=False;start+=heading.end();body=whole[start:]
        elif heading and not body[heading.end():].strip():
            section='history';offset+=len(line);continue
        if not whole.strip():offset+=len(line);continue
        # A question, conditional or relative's statement can govern later clauses
        # in the same sentence. Only split on sentence endings, not on semicolons.
        for span in re.finditer(r'\S[\s\S]*?(?:[.!?](?=\s|$)|$)',body):
            text=span[0].strip()
            study=None
            tag=re.fullmatch(r'(?:For study |Study )(NCT\d{8})(?:,|:)\s*(.+)',text,re.I)
            if tag:study,text=tag[1].upper(),tag[2]
            lo=offset+start+span.start();hi=offset+start+span.end()
            if re.match(r"^(?:(?:his|her|the patient's|my|their) (?:mother|father|wife|husband|sister|brother|son|daughter)|family member)\b",text,re.I):
                relative=True
                continue
            if re.match(r"^(?:the patient|patient)\b",text,re.I):relative=False
            if relative:continue
            yield text,section,study,(i,lo,hi)
        offset+=len(line)

def walk(raw):
    from record_facts import facts,symptoms
    from note_adapter import abstract
    from clinical_fields import from_line
    from stroke_episode import patient_stroke_findings
    for key, value, spans in patient_stroke_findings(raw, segments, consent_findings):
        yield finding(key, value), spans
    eligible=[]
    for text,section,study,span in segments(raw):
        if section in BLOCK or UNCERTAIN.search(text):continue
        eligible.append((text,span))
        prior=from_line(text) if not study else None
        if prior:
            field,value,tag=prior
            yield Finding(field.facts[0],value,field,tag),[span]
        for item in [*interpret(text,section,study),*facts(text,section,study),*symptoms(text,section)]:
            if item is not None:yield item,[span]
    if not eligible:return
    numbered='\n'.join(f'{i}. {text}' for i,(text,_) in enumerate(eligible))
    known,group=abstract(numbered)
    if group:return
    retained={'skin_condition','hospital_admission','active_treatment_of_any_form_not_considered',
              'immune_deficiency','male_or_female','woman','explicit_woman_description','pregnant','age_years'}
    for key,(value,ids) in known.items():
        if key in retained:
            spans=[eligible[i][1] for i in ids]
            yield Finding('quantity:age-at-presentation' if key=='age_years' else key,value),spans
