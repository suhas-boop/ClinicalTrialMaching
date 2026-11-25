# PocketMD: combined replay of three opt-in policies

The **strict replay remains 6/91** on the same publisher split. The separately
reported **R21 arm reproduces 8/91 with exam terminology (public case 186) and
user interpretation (case 706) only**, not R14's literal cohort policy.

| Mode | Physician-agreeing results |
|---|---:|
| Strict; none of the three policies | 6/91 |
| Literal synthetic cohort only (R14 case 322, also implemented in R21) | 7/91 |
| Exam terminology and literal cohort, no user interpretation | 8/91 |
| R21: exam terminology and user interpretation, no literal cohort | 8/91 |
| All three opt-in policies | **9/91** |

Verified by running the policies on the same 134 original inputs, not adding
aggregate scores. No prior definitive result was lost, no definitive result
disagreed with a definite physician reference, and none of the 43 indeterminate
reference cases became definitive. No independent held-out or clinical ground
truth was used beyond the published annotations; these are retrospective
development results. The combined mode still has 82 pending physician-definite
cases: 60 missing evidence, 11 authoring holds, 5 investigator actions,
4 source-scope holds, and 2 patient responses.

- 186 uses an optional adult examination terminology policy, not a measured
  pulse. This does not extend to the respiratory criterion (187).
- 322 is restricted to the literal adult description in a verified public
  synthetic vignette. R21's own stricter implementation handles this, so R14's
  case is **not** an additional fourth gain. Neither approach is a clinical
  demographic or reproductive-health rule.
- 706 uses the user's affirmative interpretation, not an interpretation
  independently verified against an internal sponsor protocol or clause.

Compared with the earlier R13/R14 package, R21 reroutes three nondefinitive
cases (55, 218, 437) from authoring hold to missing data. These are not new
definitive decisions. R15's deferred-CT patch changed routing only and its
older native/prose hunks do not apply cleanly to this codebase; it was not
grafted into the R21 score. Neither R15 nor the combined run closes case 460.

## Reproduce in an isolated R21 copy

1. Use Python 3.11+ and the original R21 release's public TrialGPT fixture.
   Do not load private patient inputs. The original R21 replay requires its
   usual dependency set; install `duckdb==1.5.0` for the publisher Parquet.
2. Copy `combined_replay.py` to `nih_benchmark/reconcile/` under the
   extracted R21 project. It calls the existing R21 and literal-scope runners.
3. From the R21 root run
   `python -B nih_benchmark/reconcile/combined_replay.py ../new-results`.
   The output directory must not exist. Check R21's existing tests with
   `python -B -m unittest discover -s nih_benchmark/round21`.

All 134 annotations, original synthetic note strings and hashes, trial IDs
and verbatim criterion text/types were verified against the packaged NCBI
publisher split. Only input columns were used during scoring preparation;
reference labels were joined after the predictions were frozen. This ZIP
contains the replay script and sanitized JSON results only. No raw note text,
private chart, personal identifier or deployment is included.

Sources: [NCBI TrialGPT Criterion Annotations](https://huggingface.co/datasets/ncbi/TrialGPT-Criterion-Annotations);
[TrialGPT primary study](https://doi.org/10.1038/s41467-024-53081-z).
