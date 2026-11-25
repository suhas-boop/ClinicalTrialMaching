"""Preserve a linked stroke episode and distinguish explicit post-imaging symptom attribution."""
import re


STROKE = r"(?:acute )?(?:cryptogenic|isch(?:e|ae)mic) stroke"
PERSON = r"(?:the patient|this patient|he|she)"
DEMOGRAPHIC = (
    r"(?:(?:[a-z'-]+ is )?(?:a |an )?)?[0-9]{1,3}[- ]year[- ]old "
    r"(?:woman|man|patient|male|female)(?: with (?P<comorbid>[a-z0-9 ,'-]+?))?(?:,? who)?"
)
DIAGNOSIS = re.compile(
    rf"(?:(?:{PERSON}|{DEMOGRAPHIC}) (?:was (?:hospitali[sz]ed|admitted) for|"
    rf"was (?:discharged|diagnosed) with|had a final diagnosis of)|"
    rf"the (?:final|discharge) diagnosis for (?:this|the index|the presenting) (?:admission|episode) was) "
    rf"(?:a (?:discharge |final )?diagnosis of )?(?:an? )?(?:confirmed )?{STROKE}"
    r"(?: (?:\w+ (?:days?|weeks?) ago|at this (?:admission|presentation)|today|yesterday))?"
)
AMBIGUOUS = re.compile(
    r"\b(?:family|mother|father|husband|wife|partner|daughter|son|sibling|sister|brother|"
    r"possible|potential|suspect(?:ed)?|probable|differential|question|risk|if|plan|denied|"
    r"without|rule[ds]? out|history|prior|previous|remote|mimic)\b"
)
ANCHOR = (
    r"(?:at (?:the|that) time|during (?:this|that|the same|the index) "
    r"(?:admission|hospitali[sz]ation|episode)|for (?:these|those|the presenting|the index) symptoms)"
)
MODALITY = (
    r"(?:(?:brain|head|cranial|cerebral) (?:ct(?: scan)?|mri|computed tomography|magnetic resonance imaging)|"
    r"(?:ct(?: scan)?|mri|computed tomography|magnetic resonance imaging)(?: of (?:the )?(?:brain|head))?)"
)
RESULT = (
    r"(?:normal|unremarkable|performed|completed|"
    r"(?:negative for|no(?: evidence of)?) (?:brain|intracranial|cerebral) (?:h(?:ae|e)morrhage|bleeding)|"
    r"(?:an? )?(?:acute |cerebral |ischemic |ischaemic )*(?:infarct(?:ion)?|ischemic stroke|ischaemic stroke))"
)
THERAPY = (
    r"(?:,? and (?:he|she|the patient) (?:was (?:given|treated with)|received) "
    r"(?:thrombolytic therapy|thrombolysis|alteplase|tenecteplase)"
    r"(?: with resolution of (?:his|her|the) symptoms)?)?"
)
IMAGING = re.compile(
    rf"{ANCHOR},? (?:an? |the |her |his )?(?P<modality>{MODALITY}) "
    rf"(?:was|showed|demonstrated|revealed|confirmed) (?P<result>{RESULT}){THERAPY}"
)
BRAIN = re.compile(r"\b(?:brain|head|cranial|intracranial|cerebral)\b")
POST_IMAGING_ATTRIBUTION = re.compile(
    r"after (?:review(?:ing| of) )?(?:the |this |a |an )?"
    r"(?P<modality>(?:brain|head|cranial) (?:ct(?: scan)?|mri)|(?:ct|mri) of the (?:brain|head)),? "
    r"(?:the final assessment|the final neurologic(?:al)? assessment|neurology|the neurologist) "
    r"attributed (?:the|this patient['’]s) presenting (?:neurologic(?:al)? )?symptoms to "
    rf"(?:an? )?(?P<cause>{STROKE}|(?:non[- ]?vascular) (?:cause|origin|etiology))"
)
STROKE_CONTEXT = "documented-stroke-episode-with-linked-brain-imaging"
NONVASCULAR_ATTRIBUTION = "neurologic_symptoms_nonvascular_origin_after_ct_or_mri"
# Extraneous text is classified only to disambiguate the episode, and never
# contributes evidence of its etiology. Require every content token to be
# accounted for in an unrelated clinical observation or follow-up instruction.
# This lets additional unparsed information invalidate an otherwise valid pair.
INCIDENTAL_SECTIONS = {
    "vitals", "vital signs", "exam", "physical examination", "laboratory", "labs",
    "laboratory results", "medications", "current medications", "follow-up", "follow up",
}
EPISODE_SECTIONS = {"", "assessment", "hospital course", "presentation", "imaging", "discharge diagnosis"}
REVIEW_TERM = re.compile(
    r"\b(?:vital signs|blood pressure|temperature|pulse|heart rate|respiratory rate|oxygen saturation|"
    r"weight|height|bmi|bp|hr|rr|spo2|sodium|potassium|glucose|creatinine|hemoglobin|"
    r"haemoglobin|platelets?|leukocytes?|cbc|hgb|hb|blood count|cholesterol|albumin|bilirubin|"
    r"ecg|ekg|electrocardiogra(?:m|phy)|sinus rhythm|echocardiogra(?:m|phy)|"
    r"angiogra(?:m|phy)|ultrasound|radiograph|x-ray|urinalysis|cardiac exam|lung exam|"
    r"chest pain|palpitations|dyspnea|shortness of breath|abdominal pain|cough|wheezing|"
    r"dysuria|edema|rash|nausea|vomiting|diarrhea|constipation|follow[- ]up|appointment)\b"
)
# Only lexical material that can qualify the unrelated observation is ignored.
# Unknown symptoms, changed assessments, pronoun-only revisions, and unspecific
# new presentations are outside this vocabulary and require a fresh review.
MODIFIERS = set("""
a an the his her she he they patient this that is was are were has had have and or with of
to from for in at by on per without no not any currently recent today now seen presents
presented reports reported history occasional intermittent mild stable regular normal
unremarkable abnormal high low normality elevated decreased negative positive clear intact
measured recorded demonstrated found showed revealed evidence abnormalities findings
resting fasting sitting standing room air current routine serum plasma blood count panel
bpm beats breaths min minute minutes sec seconds hour hours days weeks mm hg mmhg c f
percent g dl l mg mmol kg cm kgm2 lead magnetic resonance computed tomographic
transesophageal transthoracic transoesophageal arterial great vessels neck carotid
lasted lasting few then stopped stopping resolved own their spontaneously
scheduled arranged planned due repeat outpatient primary care clinic next visit
one two three four six twelve months month
""".split())
SAFETY_REVIEW = re.compile(
    r"\b(?:other patient|another|second episode|contralateral|recur\w*|new|"
    r"neurolog\w*|focal|weakness|numbness|aphasi\w*|speech|confus\w*|seizure|"
    r"migraine|stroke|tia|infarct\w*|mimic|diagnos\w*|revok\w*|withdraw\w*|"
    r"alternat\w*|instead|revis\w*|correct\w*|uncertain\w*|suspect\w*|"
    r"possibly|possible|error|however|but|despite)\b"
)
MEDICATION_ITEM = re.compile(
    r"(?:[a-z][a-z-]+ ){1,3}\d+(?:\.\d+)?\s*(?:mg|mcg|g|units?)"
    r"(?: (?:by mouth|orally|iv|po))?(?: (?:daily|nightly|bid|tid|once daily|twice daily))?"
)


def linked_imaging(text):
    match = IMAGING.fullmatch(text)
    return match and BRAIN.search(match["modality"] + " " + match["result"])


def incidental(text, section, consent_findings):
    if SAFETY_REVIEW.search(text) or section not in EPISODE_SECTIONS | INCIDENTAL_SECTIONS:
        return False
    if consent_findings(text, None):
        return True
    if section in {"medications", "current medications"}:
        return all(MEDICATION_ITEM.fullmatch(item.strip()) for item in re.split(r",|;", text))
    if not REVIEW_TERM.search(text):
        return False
    if BRAIN.search(text):
        # A normal vascular test may be an ancillary result. A second report
        # about brain parenchyma could change the assessment.
        if not (re.search(r"\bangiogra(?:m|phy) of (?:the )?(?:brain|head)\b", text)
                and re.search(r"\b(?:normal|no (?:evidence of )?abnormalities)\b", text)):
            return False
        text = re.sub(r"\b(angiogra(?:m|phy) of (?:the )?)(?:brain|head)\b", r"\1", text)
    rest = REVIEW_TERM.sub(" ", text)
    words = set(re.findall(r"[a-z]+", rest))
    return words <= MODIFIERS and not re.search(r"[?;]", rest)


def patient_stroke_findings(raw, segments, consent_findings):
    """Yield context and adjudication separately, each with the spans that establish it."""
    from record_facts import DIAG
    from prose import SECTIONS, parts as terms
    from clinical_fields import from_line
    if not re.search(rf"{STROKE}|non[- ]?vascular", raw, re.I):
        return
    sections = SECTIONS | INCIDENTAL_SECTIONS | EPISODE_SECTIONS
    statements = list(segments(raw, allowed_sections=sections))
    # Suppressed relatives/unsupported headings can contain a different subject
    # or diagnosis. Only numbering, whitespace and known headings may be omitted.
    masked = list(raw)
    for _, _, study, (_, lo, hi) in statements:
        if study:
            return
        masked[lo:hi] = " " * (hi - lo)
    for line in "".join(masked).splitlines():
        residue = re.sub(r"^\s*(?:\d+\.\s*)?", "", line).strip().lower()
        if residue and (not residue.endswith(":") or residue[:-1] not in sections):
            return

    episodes = {}
    attribution = None
    for i, (source, section, _, _) in enumerate(statements):
        text = " ".join(source.lower().split()).removesuffix(".")
        direct = from_line(source)
        if direct and NONVASCULAR_ATTRIBUTION in direct[0].facts:
            # The ordinary field reader emits this independent assertion. A
            # disagreeing narrative result must reach the matcher as well.
            continue
        assessment = POST_IMAGING_ATTRIBUTION.fullmatch(text)
        if assessment:
            if attribution is not None or section not in EPISODE_SECTIONS:
                return
            attribution = (i, assessment["cause"].startswith("non"))
            continue
        diagnosis = DIAGNOSIS.fullmatch(text)
        if diagnosis and not AMBIGUOUS.search(text):
            if diagnosis["comorbid"] and any(term not in DIAG for term in terms(diagnosis["comorbid"])):
                return
            kind = "diagnosis"
        elif linked_imaging(text):
            kind = "imaging"
        elif incidental(text, section, consent_findings):
            continue
        else:
            return
        if section not in EPISODE_SECTIONS or kind in episodes:
            return
        episodes[kind] = i

    if not episodes and attribution is not None:
        idx, nonvascular = attribution
        yield NONVASCULAR_ATTRIBUTION, nonvascular, [statements[idx][3]]
        return
    if set(episodes) != {"diagnosis", "imaging"}:
        return
    dx, scan = episodes["diagnosis"], episodes["imaging"]
    if abs(dx - scan) != 1:
        return
    # Mixed subject references in a diagnosis/report pair make the link ambiguous.
    pair = " ".join(statements[i][0] for i in (dx, scan))
    if re.search(r"\b(?:she|her|woman|female)\b", pair, re.I) and re.search(
            r"\b(?:he|his|him|man|male)\b", pair, re.I):
        return
    if scan < dx and not re.match(r"(?:during this |for the presenting |for the index )", statements[scan][0], re.I):
        return
    spans = [statements[i][3] for i in sorted(episodes.values())]
    yield STROKE_CONTEXT, True, spans
    if attribution is not None:
        # The explicit assessment names the presenting symptoms, interpreting
        # clinician and completed brain imaging. A discharge diagnosis, infarct
        # or treatment response by itself supplies no causal assessment.
        idx, nonvascular = attribution
        if idx > max(dx, scan):
            yield NONVASCULAR_ATTRIBUTION, nonvascular, [statements[idx][3]]
