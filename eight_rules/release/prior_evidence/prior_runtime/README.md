# PocketMD four-site protocol baseline

These are the four named site packets Suhas uploaded. This release inventories 114 numbered initial-screening criteria, runs a subset of their rules on normalized synthetic records, and exposes the remaining rule-authoring work. A site protocol can include other tumor types. Tumor-specific and cohort-specific obligations remain in the source packet. The previous Washington University and Levine development trials are a separate regression resource.

| Protocol | Inclusion | Exclusion | Rule paths exercised here | Authoring pending in this runtime |
|---|---:|---:|---:|---:|
| Michigan, March 2025 | 3 | 0 | 3 | 0 |
| SOTIO 106S01, Amendment 1 | 22 | 20 | 14 | 28 |
| NEOK001-1, Amendment 2 | 10 | 28 | 3 | 35 |
| REC-1245-101, version 5.0 | 13 | 18 | 2 | 29 |

A rule path may still have an interpretation hold. In coverage.json three Michigan adapter paths and fourteen sponsor research rules are distinguished from five paths with known holds. These figures measure research implementation. Independent reviewer agreement, hospital feed performance, and clinical performance still need evaluation. Consent, assent, enrollment procedures, cohort openings and amendments must also be tracked before any operational trial disposition.

## Trial onboarding and coordinator clarifications

At upload, the CLI verifies the protocol bytes, records the original timestamp, and presents the registered trial questions for the coordinator. Keep one profile per site and amendment. The coordinator can record an answer, authority, and date in that profile and refer a question to the sponsor when needed. Pass the completed profile to the authoring command to include the answer with the relevant criterion. The answer is additional source context and still requires rule validation. Patient-specific missing data stays with the patient screen.

```sh
python3 onboarding.py 106S01 "/path/to/SOTIO-site.zip" site-c303.json --timezone America/Los_Angeles --test-cycle-start
python3 packet.py 106S01-I18 "/path/to/SOTIO-site.zip" progression-packet --onboarding site-c303.json
python3 screen.py 106S01 --bundle patient-bundle.json --patient patient-id --encounter screening-visit --onboarding site-c303.json
```

For testing, enabling `--test-cycle-start` fixes cycle 1 day 1 at the site's upload calendar date plus seven days. A repeated upload to the same profile preserves both the original date and recorded answers. Subsequent screens use that same date and continue to use the run clock for evidence availability. Omit the test flag when creating an ordinary profile. A simulated date represents a study testing assumption. It does not record an actual patient dose, consent or enrollment. The included example models onboarding on November 19, 2026 in Los Angeles with a November 26 cycle start.

SOTIO I15 uses the simulated date to reject an ECG collected on or after cycle 1 day 1 as a screening ECG. SOTIO I08 and I12 also evaluate a seven-day calendar window for both the collection and release of final blood-count and albumin results. The normalized lab fixture uses Observation.effectiveDateTime as collection time and issued as the site's available report time. Both mappings need site verification. SOTIO E04 evaluates a normalized, source-linked complete transfusion history. A recent actual red-cell administration at day minus 14 triggers exclusion. An open history window, a same-day event without a dose time or no review yields MISSING_DATA. All three currently consume the simulation profile. Actual patient dose integration and independent screening schedule validation remain open. The package exposes known questions on intake; newly discovered protocol ambiguities can be added to coordinator_questions.json. No external message is sent.

SOTIO I04 carries the INVESTIGATOR_ACTIONS workflow category on every result. The workflow status distinguishes an outstanding investigator assessment, a completed assessment, and evidence that needs verification. The patient outcome is reported separately. SOTIO I04 evaluates a signed investigator estimate in UCUM months or years, including explicit bounds. An absent estimate or a bound spanning three months requests investigator clarification. The local assessment code is synthetic.

SOTIO I05 also records the investigator as the person responsible for the experimental-therapy candidacy judgment. A documented assessment closes the action for either outcome.

## SOTIO I06 tumor tissue and LRRC15

This criterion combines the patient's tissue options with a central laboratory result. The two arms of the trial use the same LRRC15 threshold. For the result to qualify, at least 1% of cells in the tested sample must stain at intensity 1+ or greater. The percentage and intensity must describe the same cells. The rule reads a final, versioned central report, its study assay order, the indexed tumor, the tested specimen and the linked quantitative IHC result. The shared catalog identifies each normalized input. The laboratory identifiers, assay and specimen terminology in the included bundle are synthetic. A site crosswalk and independent clinical validation are pending.

| Evidence available | Output for I06 |
|---|---|
| Qualifying fresh tumor biopsy and an in-window final central IHC result | MET or NOT_MET according to the inclusive threshold |
| Adequate archived FFPE block or unstained FFPE slides, with a documented safety or accessibility reason precluding fresh biopsy | Apply the same central IHC threshold |
| Only an otherwise qualifying archival report, with an explicitly feasible fresh biopsy | Protocol hold SOTIO-I06-ARCHIVE for coordinator or sponsor clarification |
| Archived sample with no documented fresh-biopsy feasibility assessment | INVESTIGATOR_ACTIONS |
| Open prescreen, adequate archive documented unavailable, willingness unknown and no pending assay order or known contraindication | PATIENT_SURVEY |
| Willing patient awaiting a result, incomplete provenance, unacceptable sample or unverified central report | MISSING_DATA |
| Documented lack of an adequate archive and a verified patient refusal of fresh biopsy | NOT_MET when the current attempt has no conflicting trial assay in progress |

The study uses a prescreening window of up to 90 days. This fixture measures the calendar-day difference in the site time zone using the actual signatures of the prescreening and main consent forms. During an open prescreen the cutoff is the provisional end. Formal screening requires the real main consent date and central result release before the first screening assessment. The onboarding clock and simulated first cycle date do not supply these events. A historical archival specimen may predate prescreen consent. Fresh collection and the trial assay order require the actual prescreen consent. A fine-needle aspirate cannot supply a qualifying result.

The fixture uses a distinct EpisodeOfCare for each attempt, linked prescreen and screening encounters, a versioned central result on the study order, and a patient-reported QuestionnaireResponse. A normalized signature event references the corresponding signed document. The test feed binds the submitted tissue preparation and the joint staining measurement explicitly. Reports that require free-text interpretation, alternate respondent profiles and regional procedures that require a separate clinical performance study plan still need validation against site data. [FHIR R4 DiagnosticReport](https://hl7.org/fhir/R4/diagnosticreport.html) · [Specimen](https://hl7.org/fhir/R4/specimen.html) · [QuestionnaireResponse](https://hl7.org/fhir/R4/questionnaireresponse.html)

Run the included boundary case on the normal command line. The I06 result is MET at exactly 1%. The complete versioned references are in its evidence list.

```sh
python3 screen.py 106S01 --bundle demo-sotio-i06.json --patient demo --encounter screen --timezone UTC --as-of 2026-11-19T19:00:00Z
```

The authoring packet includes the signed amendment's activity schedules and footnotes (pp. 21–22 and 24–25), the prescreen timing for both trial parts (pp. 38 and 43), criterion 6 (p. 47), the screening prerequisite (p. 61), and the assay and specimen instructions (pp. 65–66). At intake, record the coordinator's answer about the archival-only case with its authority and date. The authoring packet carries that answer into the next rule review.

For I06, `packet.py` now includes the original question, its protocol location, two otherwise identical archival cases and the permitted interpretation choices in `clarifications`. Both cases have a qualifying central result. One has a documented unsafe fresh biopsy and the other has a safe, accessible biopsy. The second case stays on authoring hold in this release. A coordinator can add `interpretation` and `source_reference` alongside the existing `answer`, `authority` and `decision_date` fields on the onboarding question. The packet records each applicable answer, scopes it to the criterion and exact protocol hash, and computes a reproducible context version. A bare yes/no to this two-part question requests clarification. A sourced choice goes to rule validation. The patient evaluator uses the published rule until a reviewed revision passes its cases.

## SOTIO I07 agreement about other interventional trials

Signed Amendment 1, page 47, item 7 requires an agreement about other interventional clinical trials during enrollment, with an exception for the survival follow-up period. During initial screening the executable reads a source-attributed, versioned response to that precise question. A general consent signature or a record of participation in another study cannot establish the answer. Item 2 handles the distinct requirements for informed consent and assent.

| Screening evidence | I07 result |
|---|---|
| Adult participant explicitly agrees or declines | MET or NOT_MET |
| A verified legal representative agrees or declines on behalf of a participant under 18 | MET or NOT_MET |
| The required respondent has yet to answer | PATIENT_SURVEY, addressed to the adult participant or the minor’s legal representative |
| A representative agrees and the adolescent has a recorded objection | INVESTIGATOR_ACTIONS to reconcile the responses |
| An existing response has an unverified respondent, conflicting answers or different wording | MISSING_DATA to verify the existing record |

The versioned survey and normalized evidence bindings are under `agreement_forms` in `catalog.json`. The local questionnaire codes and authority records are synthetic. The FHIR R4 binding uses QuestionnaireResponse.source for the respondent and allows staff to record an answer as author. A representative response needs the patient link, an active role for the relevant date and documented authority for the screening attempt. A parent relationship alone is insufficient. The operator uses the site calendar date during the screening encounter and checks the age band when the response was given. The included example uses a 17-year-old whose verified legal representative agrees. [FHIR R4 QuestionnaireResponse](https://hl7.org/fhir/R4/questionnaireresponse-definitions.html) · [RelatedPerson](https://hl7.org/fhir/R4/relatedperson-definitions.html)

```sh
python3 screen.py 106S01 --bundle demo-sotio-i07.json --patient demo --encounter screen --timezone UTC --as-of 2026-11-19T12:00:00Z
```

## Which day counts as screening?

For a current prescreen, omit `--as-of`. PocketMD captures the clock once per evaluation and reports the run's calendar day in `screening_date`. Live runs use the computer's local time zone by default. Set `--timezone America/Los_Angeles` (or the appropriate site zone) if the host uses a different zone. For a replay, pass an offset-qualified `--as-of`; its original offset defines the calendar day unless a zone is specified. The Michigan adapter also accepts its original calendar-date replay format and requires a snapshot frozen for that run. Its evidence checks have calendar-day precision.

The sponsor evaluators use the exact cutoff to exclude records or reports released later that day. The NEOK screening-age criterion uses the screening day. Instrument selection for a previously recorded performance assessment still uses the documented encounter date. Keep consent signatures, specimen collection, treatment starts, first dose and rescreening attempts as distinct chart or scheduling events. A run does not imply that one of those events occurred. SOTIO's cross-check against an independently documented first dose remains an open implementation item.

## Run the synthetic example

Unzip the package. Use Python 3.10 or later from the extracted directory.

```sh
python3 verify.py
python3 normalize.py demo-input.json normalized.json
python3 screen.py NEOK001-1 --bundle normalized.json --patient demo --encounter screen --as-of 2026-05-01T19:00:00Z
python3 michigan.pyz --demo all-met --trace
```

The NEOK example satisfies age and ECOG. Its three screening QTcF values are 468, 470 and 471 ms. It returns an authoring hold for that rule and identifies unimplemented criteria independently. An authoring hold is a protocol/rule question. Missing patient evidence and a patient-specific investigator action have separate meanings. Output groups are MET, NOT_MET, MISSING_DATA, INVESTIGATOR_ACTIONS, and PATIENT_SURVEY. Unimplemented rules and interpretation holds are collected in pipeline_holds. SOTIO I06 can generate a patient survey during an open prescreen. I07 routes its screening survey to the respondent designated by the protocol. A result for one criterion cannot establish trial eligibility.

## Patient evidence and terminology

The two pipelines share a versioned catalog. In this release normalize.py demonstrates one exact, synthetic local-code mapping with retention of the local coding alongside LOINC 89247-1. The score remains an integer. A different test label, a code from another hospital or a generic QTc is insufficient. QTcF uses a method-specific synthetic local code. It accepts exact UCUM ms or s and normalizes to ms. Role and history codes are also synthetic. No hospital crosswalk is verified. The importer is scoped to an already normalized research Bundle with an external versioned source archive. It does not extract charts or write transformed resources to a live FHIR server.

* Patient and Encounter carry versioned patient identity, birth date, screening date, study identity and visit. Non-Michigan examples assume a trusted study screening encounter. Full scheduling and first-dose reconciliation across the four protocols is outstanding.
* Observation carries test, method-specific coding, value, event time, release time, visit, and source document. An explicit personal or family history is distinct from a silence in the chart.
* DocumentReference links to the same patient and exact source version. PractitionerRole identifies the investigator or sponsor medical monitor on a dated study assignment. A sponsor's ECOG-2 decision must refer to the specific ECOG-2 observation.
* Michigan's existing adapter additionally uses Condition, CarePlan, medication orders, administrations and measurements linked to the indexed disease or course. It retains its original catalog and separate calendar-day input contract. Cross-adapter catalog migration is pending.
* External site and sponsor state belongs in a versioned study/site/cohort record with the authorization, effective interval and source. A patient's FHIR chart cannot prove cohort opening or a regulatory clearance. No site state was fabricated here.

For a real feed, version the site's exact code system, code, meaning, method, units, transformation and reviewer. Prefer verified LOINC for assays, UCUM for measurements, RxNorm for drug identities and validated disease/histology terminology where appropriate. Represent the regimen, course, intent and administrations independently of the drug code. Preserve local source evidence. Give unverified mappings a terminology hold. Extend the patient model only where existing resources and relationships cannot retain a distinction that changes a frozen outcome.

## Author the remaining rules

inventory.json holds each numbered clause, its scope, protocol version/hash and source location. It also indexes the 31 earlier REC blueprints. rec_contracts.json preserves all 233 previously audited candidate evidence contracts, including context and external-state requirements. Their original limitations are retained. A mapping hypothesis alone does not execute a criterion.

Use packet.py to bind a proposed rule to the actual uploaded archive. PDF page rendering requires PyMuPDF. For Michigan the authoring packet uses the Word paragraph and its existing governing passages. The original sponsor protocols remain in their site archives.

```sh
python3 packet.py 106S01-I03 "/path/to/SOTIO-site.zip" sotio-ecog-packet
python3 packet.py NEOK001-1-E15 "/path/to/NEOK-site.zip" neok-ecg-packet --context-page 70 --context-page 71
```

The default PDF range is a conservative range from the numbered criterion through the next numbered start. Review the original page, cross-references, schedule footnotes, and cohort or regional limits. The SOTIO PDF's text layer omits whole phrases, including the ECOG-2 exception. Rendered pages control if extracted text differs. Secondary summaries and older consent templates cannot resolve protocol wording. Optional --review accepts an attributed JSON answer scoped to the criterion and exact protocol hash, suitable as additional authoring context. This records the answer in a packet. It neither authenticates the reviewer nor automatically promotes a rule.

For each remaining rule, freeze positive, negative, boundary, exception, missing-evidence and wrong-patient/episode examples. Generate the typed rule from the source and governing passages, review the source obligations independently, bind each fact to verified catalog evidence, and replay it on the same FHIR entry point as earlier rules. Only count the rule as complete once every applicable branch has passed. Keep a reviewer queue for protocol ambiguity and a separate evidence queue for missing patient data. This release uses saved human-authored research rules. Fresh LLM rule generation and blinded chart extraction have not been evaluated.

The next engineering work can proceed independently of the ECG question. Bind dated drug administrations and care plans to their disease episode, indication, treatment line and setting. Start with the NEOK sarcoma branch under I03. Freeze two otherwise identical cases with four versus five prior lines in the advanced/metastatic setting and test an adjuvant line separately. Preserve the common no-standard-therapy condition and cohort restrictions. Then drive the renal and hematology predicates from each protocol's schedule and units. For REC, jointly test adolescent site permission, consent time, weight and tumor subtype. Include the locally confirmed molecular report for Ewing disease where required.

## First protocol question

NEOK001-1 Amendment 2, §5.2 exclusion 15 sets the QTcF boundary at 470 ms. Table 4 footnote k and §8.3.4 require triplicate screening ECGs at least a minute apart and completed within ten minutes. For readings of 468, 470 and 471 ms, which value governs exclusion at screening: the maximum, the arithmetic mean, or a different documented reading or repeat procedure? Please identify the governing instruction. A triplicate that straddles the cutoff remains on hold until that answer is verified.

REC uses a distinct threshold and repeat process. Its §10.6.4 specifies averaging for CTCAE grading. An average for grading must not be silently transferred to the enrollment rule. The current research implementation conservatively holds discordant results. A trial-specific screening procedure or authority answer is needed to resolve that case.

## Files and verification

screen.py executes the sponsor examples. rules.json and catalog.json identify the operators and field bindings. michigan.pyz preserves the prior executable unchanged. checks.json contains the synthetic expected and observed case results, including positive and negative examples, wrong patient, wrong source version, invalid unit, missing data, local coding and sponsor adjudication. All patient examples are synthetic. The verification command also replays Michigan through its packaged executable. The new sponsor code has been tested against local collection Bundles only. The registry count, historical contract count and individually tested rule count measure different things.
