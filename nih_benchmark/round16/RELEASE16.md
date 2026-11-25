# PocketMD evidence-backed benchmark replay

The original patient notes support six definitive decisions among 91 definite physician references. All six agree. The full set includes 134 assignments. A previously saved benchmark-only reading of one adult demographic description reproduces seven agreements. The underlying patient evidence and scores from both runs appear side by side in `nih_benchmark/round16/results/all_pairs.csv`. The optional seventh is not used to clear an actual patient. The package includes the R14 implementation and original receipts.

## Run the evaluation

    python -B nih_benchmark/round16/evidence_score.py --out replay-output

The scorer builds the patient charts, executes both interpretations for all 134 assignments and freezes their results in memory before opening the physician reference states. The reference labels, clinician-selected sentence numbers and model explanations are excluded from prediction. These are retrospective development cases. Score counts are patient–criterion pairs, not patients or trials.

A newly checked [NIST physician workbook](https://trec.nist.gov/data/clinical2014.html) covers 29 original vignettes associated with 89 assignments here. Its suggestions for differential diagnosis, investigation and treatment are separately typed. For example, a proposed diagnosis of systemic lupus and a suggested CT cannot establish a confirmed diagnosis or a performed CT. The hash-pinned source, integrity checks and reproducible joins are under `nih_benchmark/round16/physician_source`. This review added zero patient results.

## One protocol answer that could change a result

In NCT02340533 (study AD0152015), the registration lists five pelvic symptoms under one inclusion criterion. The patient describes menstrual pelvic pain, heavy periods and bleeding between periods. A related publication accepts alternatives, but the public records do not confirm that its interpretation governs this protocol version. The source comparison is in `nih_benchmark/round16/review706/706_source_crosswalk.json`.

The trial coordinator can answer the question in plain language. The fields and signature adapter included here are an engineering example for importing a verified answer. A normal written reply with the governing version and clause can be documented by a site using its usual review process.

> For study AD0152015, which combination of the five listed symptoms qualifies? Can the patient's report at screening establish the criterion, or is a separate diagnosis or assessment required? Please identify the governing protocol version and section, including any required symptom duration or severity.

No genuine response has been received. The blank question, four hypothetical answers and runnable controls are under `nih_benchmark/round16/review706`. With the original patient note held fixed, an interpretation allowing any one documented symptom without a separate diagnosis or other qualifier yields MET. The other three tested combinations leave the evidence incomplete. The scorer can take an externally verified actual interpretation as a separate, protocol-clarified arm. Keep the original-note score unchanged as the benchmark baseline.

## Tests

    python -B nih_benchmark/round16/test_literal_scope.py
    python -B nih_benchmark/round16/physician_source/test_retrospective_review.py nih_benchmark
    python -B nih_benchmark/round16/review706/test_clarify.py

The optional signed-answer tests require Python's cryptography package. Normal scoring runs offline using the standard library. `nih_benchmark/round16/results/score.json` records the verified result. R14's README covers the remaining patient-document requests and earlier experiments.
