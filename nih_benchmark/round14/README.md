# PocketMD TrialGPT R14

Run `python -B pocketmd.py trialgpt-evaluate` from the extracted package with Python 3.11 or later. The command rebuilds patient evidence from the original narratives, executes the compiled rules, then scores the results. It also runs the supplementary-source and synthetic-record experiments. No model service, hospital API or vector index is required for this replay.

## What changed

Of the 91 patient–criterion pairs with definite physician reference decisions, 79 now have executable rules, up from 76. Six yield a definite result on the original patient records. All six cite evidence and agree with the reference. The other 85 have the following primary dispositions.

| Primary disposition | Pairs |
| --- | ---: |
| More patient documentation needed | 62 |
| Rule interpretation requires a protocol answer | 12 |
| Investigator assessment needed | 5 |
| Individual patient must be identified in a group vignette | 4 |
| Patient response needed | 2 |

There were 134 assignments overall. The other 43 have a reference disposition of missing or inapplicable. All numbers here refer to pairs, not to the number of patients eligible for a trial. This is a retrospective development set. Six agreements do not estimate broad clinical accuracy.

Three previous questions could be answered from the studies' own materials. The matcher now accepts the published creatinine cutoffs in either verified reporting unit, evaluates the specified COPD exacerbation type, and distinguishes current newborn status from a history of premature birth. The patient records still leave an evidence requirement unresolved for each. The three source-linked amendments appear in `protocol_source_review.csv`. Records of the new source interpretation and its original wording are in the compiled rules. A reviewed measurement-family definition lets different trial thresholds use the same patient measurements. Case-specific boundaries are defined on the rule side.

Clinical consent and population controls also changed. Generic future consent remains distinct from current study-specific refusal, signature and capacity. An investigator-documented finding that a particular exclusion is inapplicable is kept separate from a negative diagnosis. These controls do not infer reproductive status from an administrative demographic field.

## Where to look

- `results/91_case_scorecard.csv` lists every pair in the 91, before and after rule status, the actual patient result, the physician reference, source evidence and the remaining request.
- `results/trial_questions.csv` contains the 12 remaining study-specific protocol questions for this slice. `results/record_requests_by_impact.csv` groups 102 requested record items into 58 document lookups. Ranking counts criteria a document could inform. Some require other evidence as well. The pipeline does not claim to have retrieved records from a hospital.
- `results/raw_traces.json` and `results/remaining_work.json` retain the compiled catalog hash, source digest, rule alternatives, operands and requested selectors. The full 134-row predictions are in `results/134_predictions.csv`. The 85-case audit includes retrospective R13 chart-review commentary alongside the refreshed structured traces.
- `results/scorecard.json` contains the counts. The historical eight-study sarcoma and synthetic TrialGPT evaluations have different populations. Their results are recorded separately.
- The three-amendment compilation is recorded in `../round11/compiled.json`. `approved_revisions.json` pins the six rule revisions relative to the original round 8 pack, including the three scope fixes. The eight-trial release directory retains its original sealed evaluator. The active workbench evaluator uses its baseline operators and supports alternate clinical reporting units.

## Evidence experiments

**Additional source material.** All 53 original notes were matched to the TREC organizer source using identity and content checks. Replaying all 134 assignments with the original organizer summaries added a source citation to seven cases. No criterion changed its patient outcome. The separate diagnosis experiment found official supplementary diagnoses for 15 subjects. Thirteen had assignments, covering 41 criteria. The new documents changed zero of those outcomes. Generic lupus wording could not establish the required systemic subtype. See `results/organizer_join.json`, `organizer_replay.json`, `organizer_summaries.json` and `organizer_sources/README.md`. These additions describe the same synthetic cases and are not independent clinical observations.

**Optional prescreen.** The original note described one adult patient as tachycardic and tachypneic. Two rules received `SUPPORTED_PENDING_MEASUREMENT` under the stated terminology convention. Both agree with physician reference decisions. The direct results still request the actual measurements. This policy was developed on these examples. Its portability has not been validated. Evidence and assumptions are in `results/prescreen.json`.

**Returning documents.** An independent, synthetic vital-signs report attached to the correct encounter resolved both rate criteria. With values of 90 and 20 per minute, cases 186 and 187 both became MET. A conflicting, wrong-patient or wrong-encounter record left the result unresolved. Redelivery was idempotent. A complete negative for case 187 needed evidence for its alternative routes as well. Eight scenarios and two rejected-source controls are reproducible with `python -B nih_benchmark/round14/record_arrivals.py`. Synthetic outcomes are excluded from the primary score.

**Metric sensitivity.** Across all 134 assignments, 70 executable exclusions returned MISSING_DATA. Treating that outcome as a cleared exclusion would agree with 50 additional definite references. It would also clear 18 cases whose reference was missing and two whose reference was inapplicable. This is a scoring diagnostic. The matcher never uses this imputation.

## Verification

    python -B pocketmd.py fhir-compile nih_benchmark/round11/compiled.json
    python -B pocketmd.py trialgpt-evaluate
    python -B -m unittest discover -s nih_benchmark/round14 -p 'test_*.py'
    python -B nih_benchmark/round14/organizer_sources/test_join.py nih_benchmark
    python -B nih_benchmark/round14/organizer_sources/test_summary_replay.py nih_benchmark
    python -B nih_benchmark/round13/test_changes.py
    python -B nih_benchmark/round12/test_pipeline.py
    python -B nih_benchmark/round11/test_catalog.py
    python -B pocketmd.py test
    python -B pocketmd.py verify-studies

The NIH/TrialGPT run contains 119 executable assignments across the full 134. Its synthetic mixed-branch suite exercised 748 combinations. The workbench regression suite passed 190 tests. These controls exercise implemented behavior and complement the original-note benchmark. A hospital integration must supply trusted encounter identity, source documents and their availability times. The record-arrival experiment uses a supplied encounter and a frozen snapshot; it does not establish production readiness or represent a live integration.
