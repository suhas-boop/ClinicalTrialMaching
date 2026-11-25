# Strict TrialGPT matching on the original 134 assignments

**The independent replay verified 6/91, the same as the released baseline. The target was 10.** The six retained benchmark decisions were MET on cases 44, 155, 196, 517, 577 and 633. Case 155 has a source-polarity conflict described below. All 44 original subject notes were converted through the public interface. All 44 bundles passed FHIR R4 schema validation and all 134 public CLI decisions matched the frozen predictions. [Independent score and complete differences](evaluator/verified/score.json) · [CLI verification](receipts/04-cli-parity.json)

| Strict metric | R17-descended baseline | Final release |
|---|---:|---:|
| Correct MET or NOT_MET on 91 physician-definitive assignments | 6 | 6 |
| Opposite definitive decisions on those 91 | 0 | 0 |
| Abstentions on those 91 | 85 | 85 |
| Definitive outputs on the 43 physician-indeterminate assignments | 0 | 0 |
| Abstentions on all 134 assignments | 128 | 128 |

There were zero lost baseline results and zero new definitive results. The 85 abstentions on the physician-definitive subset comprised 62 missing-data results, 12 authoring holds, five investigator actions, four source-scope holds and two patient surveys. The release added source information to nine traces. Only the chart for the subject of case 817 changed.

## Evidence available during development

We started with the R18 continuation checkpoint and reproduced the strict predictions from the later R21 reconciliation for all assignments, including each study ID and original-note fingerprint. The previous alternate-note audit covered all 44 subjects and produced no additional strict decisions. The development review used original patient narratives, assigned criteria, archived registry clauses, source-linked FHIR bundles and production execution traces. Both the predictor and the independent blind reviewer worked without physician-selected passages, rationales or eligibility labels. The scoring process checked the frozen manifest and assignment identity before opening the physician eligibility column. It read no physician rationale or selected span. Simulated responses, optional interpretation policies and trial-level outcomes contributed zero observations to the score. [Continuation checkpoint](../../nih_benchmark/round18/results/checkpoint.json) · [Alternate-source audit](../../nih_benchmark/round14/results/organizer_replay.json) · [Released replay](../../nih_benchmark/reconcile/README.md) · [Independent blind review](reviews/independent_blind_review.md)

The baseline and final audits each cover 134 assignments. Each row contains the assigned clause and polarity, registry source and matching status, closest original note passages, pertinent FHIR resources, actual catalog selectors and values, evaluated Boolean branches, decision and outstanding requests. Assigned text matched 131 archived registry clauses after whitespace normalization. Cases 307, 366 and 367 lack a verbatim registry match. Both the text-match field and historical version status are recorded per case. The six definitive assignments serve as positive controls. On the other 128, the baseline review identifies 88 missing patient facts, 15 protocol interpretation questions, 14 source-scope problems, four study actions, four investigator actions, two patient responses and one documented but unbound episode. These are first-blocker categories. A rule can have further unresolved operands. [Baseline audit](reviews/baseline_audit.json) · [Final audit](reviews/release_audit.json)

## What changed

| Case | Note line | Evidence added to the final trace | Outcome |
|---|---|---|---|
| 26 | 0 | The note describes a woman. The partial-operand citation now accompanies the existing gate citation. Pregnancy and childbearing potential remain unknown. | Abstains |
| 55 | 0 | Age two excludes current neonatal and preterm-newborn status. The pregnancy-status or documented-nonapplicability operand remains open. | Abstains |
| 132 | 0 | The women’s cohort condition binds. Pregnancy and breastfeeding remain unknown. | Abstains |
| 230 | 0 | Age 85 meets the age requirement. Symptomatic chronic subdural hematoma remains unconfirmed. | Abstains |
| 323 | 0 | Common variable immunodeficiency satisfies one conjunct. The note lacks a childhood bone marrow failure history. | Abstains |
| 454 | 0 | The note supplies age 33 and the demographic requirement. An emergency laparotomy remains unconfirmed. | Abstains |
| 460 | 5 | Total GCS 6 satisfies the first branch’s score threshold. That branch lacks a qualifying CT. The alternative lacks the required motor score and normal CT. | Abstains |
| 795 | 0 | The note identifies a pregnant woman. French-language status remains unknown. | Abstains |
| 817 | 0–1 | A source-linked observation connects the documented stroke hospitalization and head CT. The final post-imaging cause of the presenting symptoms remains unknown. | Abstains |

For the first eight, the matcher had resource references for available operands but lacked a typed list of partial source lines on the single-document screening path. Seven cases previously lacked a criterion-level sentence pointer. Case 26 already cited the gate. The shared matcher now resolves and deduplicates partial source lines for the current subject. The separate experiment with this change alone preserved all 134 dispositions. [Partial-source experiment](receipts/03-partial-source.json) · [Isolated score](evaluator/verified_partial_only/score.json)

**Case 817 was the strongest proposed decision change.** The governing exclusion reads “Subjects who have a non-vascular origin of the neurological symptoms after brain imaging (CT scan or MRI)”. The original note states “hospitalized for cryptogenic stroke two weeks ago” and then “At the time, computed tomography was negative for brain hemorrhage”. This establishes an event and imaging in that event. The baseline FHIR output lost the connection. An experimental reader bound the causal operand to false, which made the outer NOT return MET. A blind reviewer reproduced the same definitive call with a mere admission diagnosis and completed CT. The frozen candidate still scored 6/91 and made one definitive call on a physician-indeterminate assignment. The final implementation preserves the episode and its source intervals [3,129) and [133,271) as related evidence. It binds the causal operand only on documented post-imaging attribution. For the original case, the executed branch is now `NOT(unknown) → MISSING_DATA`. [Governing trial record](https://clinicaltrials.gov/study/NCT01550588) · [Intermediate score](evaluator/verified_v2/score.json) · [Final implementation and controls](receipts/04-qualified-attribution.md)

## Which branches were already decisive

| Case | Governing requirement or assigned predicate | Original note evidence | Executed branch |
|---|---|---|---|
| 44 | Excludes participants under 18 | Line 0, “58-year-old” | NOT(58 < 18) → MET |
| 155 | Publisher assigned inclusion for visible skin disease, tattoos, skin condition or abnormal skin color | Lines 0–1, “lesions on her neck” and “multiple lesions are seen” | OR(skin condition = true, other alternatives unresolved) → MET |
| 196 | Excludes age under 18 | Line 0, “40-year-old” | NOT(40 < 18) → MET |
| 517 | Excludes age under 18 | Line 0, “21-year-old college student” | NOT(21 < 18) → MET |
| 577 | Excludes moribund patients for whom active treatment of any form is not considered | Line 3, “rapid infusion of crystalloid solution followed by packed red blood cell transfusion” | NOT(AND(moribund = unknown, no active treatment = false)) → MET |
| 633 | Excludes age under 18 | Line 0, “65 yo male” | NOT(65 < 18) → MET |

**Case 155 is a benchmark agreement with a protocol conflict.** The archived NCT02615912 registry places the verbatim publisher-assigned inclusion under exclusions. The observed skin condition settles the positive OR. Applying the registry heading instead reverses its polarity. We preserved and disclosed the historical benchmark decision. [Archived registry](../../nih_benchmark/round17/registry/benchmark_2015/xml/NCT02615912.xml) · [Evidence and exact executed branches](reviews/release_audit.json)

For all 106 executable individual abstentions, we held available evidence fixed and exercised the production rule with different hypothetical completions of the missing values. Each had at least two possible outcomes. The other 22 stopped at protocol or group scope before individual evaluation. The independent review also examined OR alternatives and AND counterexamples against the original passages. It found no additional determinate case on those sources. [Boolean witnesses, case by case](receipts/05-boolean-completions.json) · [Method and replay](receipts/05-boolean-completions.md)

## Source that could change a result

**Case 706. Does the governing AD0152015 eligibility clause accept any one of the five listed symptoms without a separate pelvic-congestion diagnosis?** An applicable protocol revision and clause, or an attributable study-authority ruling, could settle the question. The archived NCT02340533 record lists the symptoms without specifying their combination. Original line 0 documents severe menstrual pelvic pain, heavy irregular periods and intermenstrual spotting. The saved affirmative user interpretation has no attached governing source. If one symptom is sufficient, the original note supports MET. If all five or a separate diagnosis are required, additional patient documentation is needed. The complete authority queue lists each case, source checked, exact question and possible outcome. [Registry](https://clinicaltrials.gov/study/NCT02340533) · [Saved protocol review](../../nih_benchmark/round20/reviews/706_protocol_review.json) · [Source questions](reviews/authority_questions.csv)

## Experiment record

1. The first candidate linked stroke and imaging. Review rejected dependence on narrowly specified surrounding prose before physician scoring. [Receipt and replay](receipts/01-single-episode-reader.md)
2. A second candidate reproduced the evidence loss on case 817 and inferred a definitive assessment. Independent counterexamples rejected that inference. [Receipt and replay](receipts/02-linked-event-attribution.md)
3. The shared matcher recovered partial-source pointers on eight abstentions. [Receipt](receipts/03-partial-source.json) · [Isolated candidate freeze](partial_only/freeze.json)
4. The shared note reader and FHIR binding preserved the documented episode and separately evaluated explicit causal attribution. Seven R12 tests, five R18 tests, four R21 tests, seven R11 tests, 190 workbench tests and eight independent attribution controls passed. [Release receipt](receipts/04-qualified-attribution.md) · [Independent controls](evaluator/verify_release_evidence.py)
5. Counterfactual evaluation tested whether the existing Boolean bindings already determined any other outcomes. It identified no additional strict decision. [Receipt](receipts/05-boolean-completions.md)

## Replay

Run the following from `/Users/admin/Documents/FHIR_PocketMD/PocketMD`. The local Python 3.11 environment runs the release and validates FHIR. The local Python 3.13 environment contains DuckDB 1.5.5 for the independent evaluator. All scoring inputs are local. The fresh directory holds the reproduced charts, full traces, manifest, CLI verification and score.

```sh
set -eu
run_dir="$(mktemp -d /private/tmp/pocketmd-strict-replay.XXXXXX)"
../.venv/bin/python -B experiments/strict_evidence/predict.py "$run_dir/predictions" --cli-check
../.venv-score/bin/python -B experiments/strict_evidence/evaluator/score.py \
  --baseline experiments/strict_evidence/baseline \
  --candidate "$run_dir/predictions" \
  --candidate-sha256 d9c178f289e77d28d16661a741230fbe0a0fbc9d1c553a5970ac6d696490cf7d \
  --out "$run_dir/score"
cmp "$run_dir/predictions/freeze.json" experiments/strict_evidence/release/freeze.json
cmp "$run_dir/score/score.json" experiments/strict_evidence/evaluator/verified/score.json
../.venv/bin/python -B experiments/strict_evidence/check_cli.py "$run_dir/predictions" > "$run_dir/cli-parity.json"
cmp "$run_dir/cli-parity.json" experiments/strict_evidence/receipts/04-cli-parity.json
../.venv/bin/python -B experiments/strict_evidence/evaluator/verify_release_evidence.py
```

| Artifact | SHA-256 |
|---|---|
| [Baseline freeze](baseline/freeze.json) | `88d1fd3fe4b48699b9a00c55aa64394a97657503db92b464f3308b2f6b485627` |
| [Final freeze](release/freeze.json) | `d9c178f289e77d28d16661a741230fbe0a0fbc9d1c553a5970ac6d696490cf7d` |
| [Final predictions](release/predictions.json) | `11dcd7fe40eb88df8912332086b85c7028ac52cdaf13737f434dc4657d7c482d` |
| [Independent score and complete differences](evaluator/verified/score.json) | `aaf91228bb72b25c4132cc9e29437fa9c0ecccdff20fcec9a2213e3dea1487de` |
