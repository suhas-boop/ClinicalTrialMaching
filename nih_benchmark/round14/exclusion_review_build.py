"""Document source-grounded next inputs on the 18 cited exclusion discrepancies."""
import csv
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
CASES={
'20':('Patient or site logistics','Study-specific confirmation of geographic access to treatment and follow-up.','General future compliance does not specify travel access.'),
'25':('Clinical record','Hypertension subtype and severity from a diagnosis or qualifying assessment.','The source says hypertension with no severity or secondary etiology.'),
'55':('Protocol reviewer','Confirm whether preterm birth history excludes an older child.','Age excludes a current neonatal state but does not establish term birth.'),
'81':('Clinical record','An infection diagnosis with severity and dates relative to screening and baseline.','Fever and lab results do not establish an active severe infection or its absence.'),
'115':('Clinical record','Documented ulcer etiology and a leishmaniasis or insect-bite assessment.','A painful oozing lesion can have more than one cause.'),
'116':('Clinical record','Documented presence or absence of a burn-related ulcer.','The note gives appearance and treatments tried, without burn attribution.'),
'130':('Protocol reviewer','Confirm whether any one listed disorder or their conjunction triggers exclusion.','Eating-related symptoms and bipolar history do not confirm or rule out the named disorders.'),
'138':('Medication history','Medication reconciliation covering prior and current qualifying antipsychotic treatment.','The list gives current medications only.'),
'179':('Procedure history','Documented central venous puncture/catheterization, or sufficient history covering prior procedures.','The catheterization in the note uses a femoral artery.'),
'212':('Consent disposition','Current study-specific written-consent acceptance or refusal.','The source records future intent without the consent form, current disposition or study identity.'),
'239':('Clinical record','Menopausal status assessment for the patient.','Age, amenorrhea and pregnancy test do not supply the documented assessment.'),
'322':('Rule authoring','Verify population scope of both branches, then test with explicitly identified study population.','Source qualifies both branches by population. Chart demographics alone do not establish reproductive state.'),
'336':('Consent disposition','Current study-specific consent log documenting refusal or presence of consent.','Future intent is consistent with no consent on file today.'),
'414':('Clinical record or clinician','Established SLE diagnosis or a qualified assessment linking the findings to diagnosis.','The note reports findings and antibodies without naming a diagnosis.'),
'544':('Protocol reviewer','Define severe cardiac condition, governing time window and required assessor.','Prior MI and current symptoms are insufficient to resolve the wording.'),
'632':('Clinical assessment','Study-specific assessment of ability to provide written informed consent.','Projected willingness does not establish written-consent capacity.'),
'850':('Clinical record','Documented weekly asthma exacerbation count or qualified assessment over the appropriate interval.','Wheezing history and the index episode do not establish the required frequency.'),
'965':('Protocol reviewer / clinical record','Clarify whether current CBC findings constitute known history, or obtain an earlier qualifying history.','The current count documents leukopenia and thrombocytopenia.')}
def main():
    rules=json.loads((HERE.parent/'round11/compiled.json').read_text())['rules']
    with (HERE.parent/'round13/85_case_audit.csv').open() as f:
        cases=[r for r in csv.DictReader(f) if rules[r['case']]['source']['criterion_type']=='exclusion'
               and r['physician_source_lines']!='[]']
    assert {r['case'] for r in cases}==set(CASES)
    with (HERE/'18_cited_exclusion_review.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['annotation','criterion','cited_note_text','r13_state','owner','r13_next_requested_input','why_citation_alone_is_insufficient'])
        for r in cases:
            w.writerow([r['case'],r['criterion'],r['physician_cited_text'],r['replay'],*CASES[r['case']]])
if __name__=='__main__':
    main()
