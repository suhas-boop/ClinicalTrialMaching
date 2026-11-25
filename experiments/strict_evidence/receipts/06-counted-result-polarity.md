# Case 155 and the six counted benchmark results

**The published strict score remains 6/91. Five of the six counted results also agree with the original trial criteria. Case 155 is the exception.** The full re-score of the frozen 134 assignments reproduced six agreements, zero opposite definitive results, 85 abstentions on physician-definitive assignments, and zero definitive outputs on the 43 physician-indeterminate assignments. An independent verifier repeated the label join and checked all six registry headings. [Machine-readable receipt](../evaluator/verified/criterion_polarity.json)

## Where the conflict enters

The original NCBI annotation for case 155 is a non-training row with patient ID `sigir-20149`, trial ID `NCT02615912`, criterion type `inclusion` and `expert_eligibility = included`. Its criterion text is “Subjects with visible skin disease, tattoos, skin condition, or abnormal skin color”. The locally scored Parquet file has the same SHA-256 as the publisher's original upload at revision `7fca07b80914df31e0ab69f9f8fd4d3c6a06d020`. Only the original eligibility label was used for scoring. [NCBI upload and file checksum](https://huggingface.co/datasets/ncbi/TrialGPT-Criterion-Annotations/blob/7fca07b80914df31e0ab69f9f8fd4d3c6a06d020/data/train-00000-of-00001.parquet)

Three study sources put that same clause under **exclusion**. The original December 16, 2015 registry XML lists the healthy-volunteer Fitzpatrick skin type requirement as inclusion, then gives the skin-condition clause as the first exclusion. The NIH TrialGPT study record explicitly stores the clause in `exclusion_criteria`, and the later ClinicalTrials.gov record retains that heading. The discrepancy is present in the published annotation pair before PocketMD maps its label. These records do not establish how the annotation acquired that polarity or how a physician would have labeled the correctly oriented question. [Historical registry XML](../../../nih_benchmark/round17/registry/benchmark_2015/xml/NCT02615912.xml) · [NIH TrialGPT study record selection](../../../nih_benchmark/round17/registry/benchmark_2015/nih_trial_info_selection.json) · [Later registry record](../../../nih_benchmark/round17/registry/benchmark_2015/current/NCT02615912.json)

The patient's original note reports “lesions on her neck” on line 0 and “multiple lesions are seen” on line 1. The frozen source-linked Observation `x-e1a9b5a654de4380eb0cc3861254f8` makes the skin-condition branch true. That single branch settles the four-way OR. With the published inclusion orientation, the result is MET and the physician label `included` maps to MET. With the registry exclusion orientation, the production evaluator applies NOT to that same true OR and returns NOT_MET on the same evidence. This finding concerns the assigned criterion only. [Frozen decision and original note lines](../evaluator/verified/criterion_polarity.json) · [Scoring map](../evaluator/score.py)

## Effect on the count

| Cases | Published assignment | Raw physician label | Frozen result | Result using trial-source polarity |
|---|---|---|---|---|
| 44, 196, 517, 577, 633 | Exclusion | `not excluded` | MET | MET |
| 155 | Inclusion | `included` | MET | NOT_MET |

For the other five, both the archived trial heading and NIH study record match the assignment. In a sensitivity check, changing only case 155's **prediction** to the registry-oriented result while holding the published physician labels fixed gives five agreements, one opposite result and 85 abstentions on the same 91. No replacement physician label was inferred. The official score and forecasts retain their original hashes.

## Replay

From the PocketMD development checkout, rerun the evaluator-only audit against the frozen predictions and independently deposited publisher data. The command checks all 134 assignment identities and the original freeze before reading the physician labels. It then reruns the six counted expressions using their frozen evidence, and runs the alternate polarity only where the source heading differs.

```sh
set -eu
run_dir="$(mktemp -d)"
../.venv-score/bin/python -B experiments/strict_evidence/evaluator/audit_criterion_polarity.py > "$run_dir/polarity.json"
cmp "$run_dir/polarity.json" experiments/strict_evidence/evaluator/verified/criterion_polarity.json
```

The [JSON receipt](../evaluator/verified/criterion_polarity.json) records both forecast-manifest hashes, the publisher, source selection and catalog checksums, and each counted case's statement, label, branch, source lines and registry fingerprint.
