# R21 user clarification for AD0152015

Suhas answered “Yes” when asked whether any one of the five listed symptoms satisfies the registered inclusion criterion without a separate diagnosis of pelvic congestion. The clarification applies to this criterion only. The source is the user's answer; attribution to a study official and the internal protocol edition and clause are undocumented. The public locator is NCT02340533, Eligibility Criteria, Inclusion Criteria, sole unnumbered bullet, registry record last posted July 28, 2015.

Case 706 now yields MET in the user-clarified run. The 38-year-old patient describes painful menstruation, heavy irregular periods and spotting between periods at the presenting visit. Those observations support dysmenorrhea, menorrhagia and metrorrhagia. Matching one symptom is sufficient. The executable rule preserves the registered population condition. The clinical note and explicit source character offsets are retained in the prediction file.

All 134 assignments were rerun, with predictions saved before physician labels were opened for comparison. The exam-evidence policy incorporating this user clarification gives 8 agreements among 91 physician-definitive assignments, zero disagreements and 83 pending. The result for 706 is the only changed disposition. The R20 exam policy alone gives 7/91. The original strict policy gives 6/91, or 7/91 when applying this user answer alone. For the existing automation, a user clarification without an independently verified governing source does not increase its historical strict score. Standalone criterion outcomes do not decide trial enrollment.

    python -B pocketmd.py user-clarified-score --out /tmp/pocketmd-user-clarified
    python -B -m unittest discover -s nih_benchmark/round21

In nih_benchmark/round21, user_answer.json preserves the source message and registry_locator.json identifies the public citation. The results directory contains the full prediction freeze, the new rule, case evidence and score. pending_83.csv contains the other open assignments for this policy.

# R20 review of criteria 187 and 706

The original policy reproduces 6 correct decisions among the 91 physician-definitive assignments. The exam-evidence policy introduced in R19 reproduces 7, including case 186. Both replays include all 134 assignments. R20 adds zero confirmed decisions or disagreements. There are 84 pending assignments under the exam-evidence policy.

**187.** The respiratory criterion is an OR. The chart supplies an adult emergency examiner’s term “tachypneic.” A policy that always applies the conventional adult definition above 20/min produces MET, which raises that experimental result to 8/91. Two published adult clinical examinations used the term with a measured 18/min. The frozen chart supplies no rate, gas result, ventilation status or controlling terminology convention. In the main exam-evidence replay 187 remains MISSING_DATA. The trial supplement also uses the term for a different component of the sepsis definition. Another patient, trial participation and textbook interpretation do not provide a measured rate for this patient.

**706.** The exam records painful menstruation, heavy periods, and bleeding between periods. The trial registry and the contemporaneous WHO mirror list five symptoms and omit the required combination. The investigator’s published methods allow alternatives, and NICE and RANZCOG reviews independently summarize the publication. No recovered document establishes that those methods govern the registered criterion. With at least one symptom sufficient and no separate pelvic-congestion diagnosis required, the patient meets the symptom criterion. The three other checked interpretations leave patient evidence missing. All four conditional verdicts and their underlying patient fact values and references reproduced. No study authority answered or was contacted. The default verdict is AUTHORING_HOLD.

The specific question for the protocol owner is: For AD0152015, is one of the five listed presenting symptoms sufficient without a separate diagnosis of pelvic congestion? If additional conditions apply, which ones? Please identify the protocol version and eligibility clause.

    python -B pocketmd.py respiratory-exam-score --out /tmp/pocketmd-r20
    python -B pocketmd.py exam-evidence-score --out /tmp/pocketmd-r19
    python -B pocketmd.py evidence-score --out /tmp/pocketmd-strict
    python -B -m unittest discover -s nih_benchmark/round20

The fixed predictions, all three scores, verification receipt, and study-specific source reviews are under nih_benchmark/round20. Earlier versions and the R19 pending list still describe the same supported cases. The two research candidates retain their prior status; revisit 187 if a verified chart rate, accepted institutional definition or alternate qualifying branch becomes available, and revisit 706 if the governing rule is located.

# R19 adult exam terminology

On the frozen 134 assignments, a separately scored evidence policy accepts adult tachycardia documented by the examiner as evidence for the standalone heart-rate comparison at presentation. Case 186 changes from MISSING_DATA to MET on that basis. Its source records age 40 and tachycardia on the present exam. A conventional adult definition supplies the open lower bound of 100/min. No exact pulse is stored. Hospital enrollment and ICU screening are separate questions. The policy is registered for the source-reviewed criterion and has not been clinically validated across sites.

The comparison yields 7 agreeing decisions out of the same 91 physician-definitive assignments, with zero disagreements. The previous strict score remains 6/91. These policies have different evidence requirements. The experimental arm does not add to the existing strict automation target. Reference labels are read only after all predictions and their new evidence are written. This is a development replay of previously reviewed cases.

    python -B pocketmd.py exam-evidence-score --out /tmp/pocketmd-exam
    python -B pocketmd.py evidence-score --out /tmp/pocketmd-strict

The round19 results include all 134 predictions, chart line and resource references for 186, the source-qualified rule, the frozen source and scoring fingerprints, and reference discrepancies. The round18 results retain the evidence for the six prior decisions. Full source links and the distinction between the registered heart-rate requirement and the ICU enrollment context are in nih_benchmark/round19/source_review.json.

# PocketMD evidence replay R18

The full replay produced six correct evidence-backed decisions on the same 91 physician-definitive criteria. All 134 individual states and all six sets of decisive citations match R17. Four more correct, source-backed decisions are needed for the target. The stored prediction file was written before the scorer opened the physician reference labels. This is a retrospective development cohort.

NIH appended a sentence about future consent and practical compliance when preparing the TrialGPT model input. The verified benchmark import now retains that sentence in the original source attachment and identifies its origin. Patient findings derived from it are omitted. Ordinary patient documents use the normal import path. Removing the sentence entirely in a separate test changed zero of the 134 outcomes.

The new source reviews cover the signed sponsor report for criterion 322, the investigator's thesis for 239, national registrations for 55 and the distinction between numeric vital signs and an examination description for 186 and 187. None supplied a missing patient fact or settled the relevant protocol branch. Criterion 706 still awaits the study authority's interpretation. A prior hypothetical answer and prior prescreens stay outside the six.

    python -B pocketmd.py evidence-score --out /tmp/pocketmd-r18-replay
    python -B nih_benchmark/round18/test_benchmark_source.py
    python -B nih_benchmark/round18/assumption_probe.py nih_benchmark /tmp/pocketmd-r18-ablation.json
    sha256sum -c SHA256SUMS

The shipped default FHIR chart was rebuilt and checked against all 134 single-case CLI executions. The historical R10 catalog-rebuild test also fails on the R17 base. Its expected archived catalog differs from a fresh compilation. The scored replay verifies and uses the frozen R11 catalog.

Look in nih_benchmark/round18/results for the prediction freeze, the original-note replay, and the continuation checkpoint. Clinical source reviews with their protocol and patient identifiers are in nih_benchmark/round18/reviews. The underlying study-level results are documented below.

# PocketMD screening replay R17

PocketMD now reports the answer to a patient–criterion question separately from the decision to continue screening a patient for a study. The original notes produced six evidence-backed criterion decisions among 91 physician-definitive assignments. All six agreed with the reference. Across the same 68 patient–study pairs, the new study screening command found six protocol restrictions that the patient failed at the documented presentation. Five concern age. One concerns the duration of the current fever. The other 62 pairs continue screening.

## Results on the original assignments

| Question | Result | Evidence file under nih_benchmark/ |
| --- | --- | --- |
| Can the original rule run? | 79 of the 91 physician-definitive assignments have executable rules. | round14/results/91_case_scorecard.csv |
| Does the original patient note yield a definite answer for that specific criterion? | 6 of 91. All six agreed and had a cited patient finding. No other assignment in the complete 134 received a definite result. | round17/results/original/definitive_evidence.json |
| Does a checked study requirement already rule the patient out at this presentation? | 6 of 68 pairs. Those six contain 13 unresolved criterion assignments, 11 of which have a definite physician reference. | round17/results/study_decision_evidence.csv |
| How did the study outcomes compare with the original assessors' referral ratings? | Of the six exclusions, three had a high referral rating and three had a conditional referral rating. All 68 selected pairs had one of these two ratings. | round17/referral_reference/trial_referral_comparison.csv |

A trial-level disposition never supplies a negative answer to an unrelated patient question. For example, NCT02467309 enrolled participants up to 18 years. The note identifies a 44-year-old patient. The protocol age limit settles screening at that time. The patient's HIV and tuberculosis histories remain unknown. TrialGPT uses synthetic patient narratives. The SIGIR trial judgments measure willingness to refer. These results do not establish clinical eligibility accuracy.

## Try the ordinary screening commands

Run from the extracted package. Python 3.11 or later supports the offline replay. The signed protocol clarification integration also uses Python's cryptography package.

    python -B pocketmd.py evidence-score --out /tmp/pocketmd-criterion-replay
    python -B pocketmd.py trial-disposition --out /tmp/pocketmd-pair-replay.json
    python -B pocketmd.py trial-disposition --study NCT02467309 --subject Patient/sigir-201512 --bundle nih_benchmark/round12/export/bundles/sigir-201512.json
    python -B pocketmd.py fhir-screen --study NCT02467309 --subject Patient/sigir-201512 --criterion 735 --bundle nih_benchmark/round12/export/bundles/sigir-201512.json

The third command returns the age evidence and the governing protocol source. The fourth requests the missing patient evidence for that individual criterion. Eligibility limits apply at the documented screening encounter. Screening may be repeated if the relevant patient evidence or protocol version changes. A continuing screen is incomplete.

## What changed in the pipeline

- The age screen binds the index person's age at presentation to a numeric FHIR Observation with the appropriate LOINC code and UCUM unit. Completed years, months and days retain their original precision. The screen checks whether the required age applies at this encounter. A historical enrollment age requires a record from that time. Group vignettes and missing provenance remain unresolved. The reviewed study enrollment passages are in round17/registry/age_scope_reviews.json.
- Original registration XML was recovered for all 68 studies in the December 2015 SIGIR collection. A comparison against the NIH release and registry records verified 61 studies for age evaluation. Seven were held for version or wording discrepancies. The implementation retains the source documents, normalization assumptions and checksums in round17/registry/benchmark_2015. A separate historical audit of all 12 remaining protocol questions found no new governing definition. [Original collection](https://doi.org/10.4225/08/5714557510C17) · [NIH TrialGPT release](https://github.com/ncbi-nlp/TrialGPT)
- The mandatory fever-duration rule uses the same numeric comparison engine. The index note gives two days, and a second passage associates the onset of fever and cough. The study requires more than seven days. It could be appropriate to screen this patient again later. The trace is in round17/results/fever_gate.json.
- A verified study interpretation for criterion 706 now runs through the ordinary FHIR matcher. The previous benchmark-only review could disagree with ordinary screening and could misread family or past medical history. The new path preserves study version, patient identity, current symptoms and exact source spans. A simulated one-symptom interpretation changed this case to MET. Three other simulated interpretations needed further patient evidence. The site has supplied no genuine clarification. The original adjudication and benchmark result remain open. All three public registry versions retain the same symptom-list wording.
- The ordinary fhir-screen command accepts encounter-linked document bundles with --encounter Encounter/id. It checks supported extracted observations against their source notes and returns document and observation IDs. Tested controls include conflicting measurements, records for the wrong encounter or person, altered values and recurring delivery. The tests for criteria 186 and 187 use simulated vital signs. Neither contributes to the original score.
- Encounter-linked multi-document screening and signed protocol clarification are separate invocation modes in this revision. The workflow supports the validated note-derived contracts in the included catalog. The package contains a research implementation, and the six study findings have no independent clinical eligibility adjudication.

## Additional patient–study combinations

The 44 assigned subjects were screened against the same 68 studies. Removing the original 68 assignments left 2,924 pairings. The code produced 104 documented age exclusions and 2,820 continuing screens. The age-exclusion path requires a reviewed population and enrollment-time anchor. Five registrations have that approved at-presentation interpretation. Of the other study/patient combinations, 616 were flagged for an age-scope review. These are new pairings of existing patients and studies, not a test on new hospitals or generally unseen study designs.

Predictions were frozen before joining published referral judgments. Only nine of the 2,924 pairs have a published judgment, seven grade zero and two grade two. All nine continued screening. The 104 exclusions had no published referral judgment. The extension demonstrates source-backed execution. Its independent labels are too sparse to validate the new exclusions. Read round17/results/expanded_summary.json for coverage and round17/referral_reference for the label comparison. [Authors' study and rating scale](https://doi.org/10.1145/2911451.2914672)

    python -B nih_benchmark/round17/expanded_screen.py --out /tmp/pocketmd-expanded

## Open study-authority question

For AD0152015 (NCT02340533), does one of the listed pelvic symptoms satisfy this criterion at screening? Does the protocol require any particular duration, a separate diagnosis of pelvic congestion, or an investigator assessment? The governing section and version would determine whether the documented symptoms resolve criterion 706. The related publication allows symptom alternatives in its cohort, while its enrollment and completion details differ from the registry. [Study history](https://clinicaltrials.gov/study/NCT02340533?tab=history) · [Related article](https://doi.org/10.1016/j.jmig.2015.11.004)

## Reproduce and verify

    python -B -m unittest discover -s nih_benchmark/round17
    python -B -m unittest discover -s nih_benchmark/round14
    python -B nih_benchmark/round16/review706/test_release.py
    python -B pocketmd.py test
    sha256sum -c SHA256SUMS

round17/results/trial_dispositions.json is the original timestamp-independent prediction artifact frozen before comparing it with study-level referral ratings. current_trial_dispositions.json contains the same 68 decisions with additional evidence-selector and study-scope citations. Prior releases' receipts are historical. The SHA256SUMS at the root covers the present release.
