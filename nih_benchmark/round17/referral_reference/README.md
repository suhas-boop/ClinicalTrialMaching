# SIGIR 2016 patient–study referral reference

`sigir_referral_reference.csv` links each of the 68 distinct patient–study assignments in PocketMD’s frozen criterion benchmark to a published trial-level referral judgment. The CSV is evaluation data. Keep it outside the prediction stage. `reference_provenance.json` records the sources, publication versions, checksums, grade dictionary, coverage and attribution.

The label is a medical assessor’s view of referral based on the case description. Grade 0 means the assessor would decline referral, grade 1 means they would consider referral after further investigation, and grade 2 means referral is highly likely. Eligibility under every protocol criterion, actual physician referral and enrollment were not measured. An absent judgment is an unassessed pair in that release. The authors pooled a limited set of ranked pairs for assessment. Treat grade 1 as its own category. These selected assignments contain no grade-zero examples, so they cannot estimate specificity against non-referrals. [Assessment protocol](https://doi.org/10.1145/2911451.2914672)

The DOI in the original paper resolves to the first collection version. The authors published four versions. We used the fourth version, published April 4, 2017. Each CSV row points to its original grade and physical line number. The NIH transformation was checked independently. Original and transformed scores agree on all shared pairs. The NIH release omits the group topic, which is present in the original source. Keep the two group–study rows separately identified when interpreting individual screening results. [Version history](https://data.csiro.au/dap/ws/v2/collections/17152/versions) · [Fourth collection version](https://doi.org/10.4225/08/58e2e83d92c2b)

The suffix of the PocketMD patient ID was matched to the original topic number. Each selected patient’s complete original vignette was verified after removing NIH’s sentence numbering and fixed consent sentence and applying the existing source-format normalization. This step establishes patient identity for the reference join. The estimator does not use study-level judgments to fill patient findings.

## Rebuild

The builder reads the assignment manifest and frozen notes from the benchmark. It verifies the original topic descriptions and both releases of the judgments. It never reads a prediction. Supply these files in the input directory.

| Local filename | Published source |
| --- | --- |
| v4_qrels-clinical_trials.txt | [Original judgments](https://data.csiro.au/dap/ws/v2/collections/22333/data/49692372) |
| v4_topics-2014_2015-description.topics | [Original patient topic descriptions](https://data.csiro.au/dap/ws/v2/collections/22333/data/49692376) |
| v4_metadata.json | [Collection metadata and rights](https://data.csiro.au/dap/ws/v2/collections/22333) |
| nih.tsv | [NIH TrialGPT judgments, pinned commit](https://raw.githubusercontent.com/ncbi-nlp/TrialGPT/1b3242cd50c153a9c324661d4a0bd94fc68a4226/dataset/sigir/qrels/test.tsv) |
| nih_queries.jsonl | [NIH TrialGPT patient descriptions, pinned commit](https://raw.githubusercontent.com/ncbi-nlp/TrialGPT/1b3242cd50c153a9c324661d4a0bd94fc68a4226/dataset/sigir/queries.jsonl) |

```sh
python -B build_reference.py --benchmark /path/to/nih_benchmark --inputs /path/to/published/files --out /path/to/evaluation/reference
```

The labeled CSV is a subset adapted from *A Test Collection for Matching Patient to Clinical Trials* by Bevan Koopman and Guido Zuccon. Rights are held by CSIRO, U.S. National Institute of Standards and U.S. National Institutes of Health, 2016. This adapted reference is distributed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).

## Frozen study-level comparison

The 68 study dispositions were frozen before their reference labels were disclosed to the prediction team. `evaluate_frozen.py` verifies both SHA-256 fingerprints before joining by topic and study. These are the protocol gate dispositions and the assessors’ referral judgments for the same cases.

| PocketMD study disposition | Would decline referral | Consider after investigation | Highly likely to refer |
| --- | ---: | ---: | ---: |
| Excluded at presentation | 0 | 3 | 3 |
| Continue screening | 0 | 30 | 32 |

Three high-referral cases had an exclusion from the registered age window. The labels provide no reason for the referral judgments. Investigate these cases against the criterion, its source version and the patient’s age at the assessment. A high referral rating can justify follow-up even when available patient facts fail a protocol gate. The 62 continued screens still require the remaining eligibility review.

```sh
python -B evaluate_frozen.py --predictions /path/to/round17/results/trial_dispositions.json
```

`trial_referral_comparison.csv` contains the joined 68 rows with source lines. `trial_referral_results.json` records the counts, artifact hashes and three high-referral cases excluded by PocketMD. Group judgments apply to the original group vignette.
