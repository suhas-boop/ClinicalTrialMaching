# Criteria2SQL development experiment 1

On development line 242, the published SQL, the exported PocketMD rule on normalized facts, and the same rule on FHIR selected the same four of six synthetic patients with complete evidence. All three rejected the two below-threshold controls. Both PocketMD paths returned `MISSING_DATA` for the seventh patient, whose chart omitted birth date. This experiment identified no discrepancy in the age comparison or FHIR binding.

## Reproduce

From the `PocketMD` directory, run the following command with Python 3.11 and a fresh output directory. This replay uses the standard library and the recorded author and reviewer judgments.

```sh
python3.11 -B experiments/criteria2sql/replay.py "$(mktemp -d)/age-replay"
```

The first process rebuilds the rule and both sets of predictions and compares their hashes with the saved freeze. A separate process executes the reference SQL and writes `score/score.json`. The command also compares the new patient-level evidence and dispositions with the independent score. The original [prediction manifest](author/frozen/freeze.json) and [independent score](evaluator/verified/score.json) contain the file hashes and patient-level evidence.

## Criterion and evidence

The criterion was “adult patients,  >  /  = 18 years of age”. The lead selected it from the 300 development texts before looking at reference SQL. It was the first explicit inclusive boundary whose complete wording fit the existing age binding. The source was development line 242, table 50, phase field `1`, at commit `045528d70a7d788775a24763adfed6c66023c914`. The published test split was reserved. [Selection record](selection.md) · [Pinned dataset](https://github.com/xiaojingyu92/Criteria2SQL/tree/045528d70a7d788775a24763adfed6c66023c914/data) · [Source verification procedure](evaluator/README.md)

The source excerpt supplies the age threshold. The synthetic comparison treats the positive wording as an inclusion predicate and uses the screening encounter's local start date as its assessment date. The source has no governing protocol or section heading. The flat records use whole-valued years in a float column. Independently specified birth dates and encounters supply the FHIR inputs. The local R4 schema accepted all seven generated bundles. [Concept map](author/concept-map.json) · [Flat records](author/controls/flat.json) · [Source charts](author/controls/chart.json)

| Synthetic ID | Age at encounter | Distinguishing evidence | Normalized and FHIR | Published SQL |
|---|---:|---|---|---|
| 101 | 17 | Day before 18th birthday | NOT_MET | Omitted |
| 102 | 18 | On 18th birthday | MET | Selected |
| 103 | 18 | Day after 18th birthday | MET | Selected |
| 104 | 19 | On 19th birthday | MET | Selected |
| 105 | 17 | Local December 31 screening before birthday, cutoff after midnight | NOT_MET | Omitted |
| 106 | 18 | Local January 1 screening after birthday | MET | Selected |
| 107 | Unknown | Missing date of birth | MISSING_DATA | Excluded from SQL comparison |

The year-end pair checks a second failure mechanism. Using the UTC calendar date or the later snapshot cutoff would give patient 105 an age of 18. The FHIR evaluator used the local encounter date and returned `NOT_MET`. Each FHIR decision cites that patient's versioned Patient and Encounter resources. The SQL comparison has six complete patients, zero definitive disagreements and zero abstentions. The missing-evidence check has one patient and one abstention per PocketMD path.

## Freeze and engineering changes

The engineer authored the candidate from the blind text and age catalog. The lead reviewed its source obligations before author export. The public `pocketmd.py author build`, `export` and `screen` commands handled the actual rule and FHIR decisions. The experiment adds a normalized-fact adapter that reads the same exported rule and reuses the workbench's catalog validation and comparison operators. The TrialGPT `fhir-screen` command accepts a different compiled rule format. The engineer and SQL verifier worked in separate directories and sessions. Both had a shared filesystem, so blinding was procedural.

The lead verified every listed input and output digest before releasing the reference to the independent verifier. The verifier executed the selected upstream query `select id from records where age >= 18` on the six complete flat records. No patient-specific code or clinical rule change was needed. [Authored rule](author/frozen/rule.json) · [Exact source row](evaluator/reference.jsonl)

| Fingerprint | SHA-256 |
|---|---|
| Prediction freeze manifest | `16ef10ce67c4504f71b8630b265bd29ba165f1ff9b7732321ef3c80a11c5a52a` |
| Canonical exported rule | `e4515195d81569f211b7f1e4b5a335437ed4a71d3b9e4a75c4b84fe9b3070280` |
| Independently verified score | `87cd804f30d7baa968d4bc64aceaeb8257bca21830e03540f35b06f410f92df7` |
| Development input file | `00dbac8202e0f3b1c8ec85dfc333c6bafb2f92e60ab3f3242bcc38a3b2a89f4b` |
| Development table file | `102ac079098d1015532752b68bdbdbc15ca98270958f118636d6d2edb5e4ac54` |

The verifier checked the complete upstream development-file hashes and Git blob IDs, the selected row bytes, the table schema, and the correspondence between the textual and structured SQL. Both SQL representations returned IDs 102, 103, 104 and 106. Negative controls rejected altered predictions, an altered freeze manifest and an existing output directory. A fresh end-to-end replay reproduced the saved evidence and dispositions.

## Historical TrialGPT regression

The R21 combined replay separately rebuilt all 134 assignments and reproduced the packaged predictions and score files byte-for-byte. Among 91 physician-definitive assignments, strict scoring gave 6 agreements, 0 definitive disagreements and 85 pending. The combined experimental policies gave 9 agreements, 0 definitive disagreements and 82 pending. Neither arm made a definitive call on the other 43 assignments. No strict disposition changed. The synthetic age experiment contributes zero patients to these denominators. [Historical score](../../nih_benchmark/reconcile/summary.json) · [Replay runner](../../nih_benchmark/reconcile/combined_replay.py)

The two supplied pipeline ZIPs had the same SHA-256, `ac2b21ef7810811c2c3f73ee47d12243159c6f05f0fe70d713faf933fac06b48`. The installer verified all 1,048 entries in the packaged manifest in the separate R21 working copy. It carried forward the three existing PyMuPDF import changes for this machine's 1.28.2 installation. The workbench passed 190 tests under Python 3.11. The archived combined replay and four R21 regression tests passed with the locally available Python 3.13 and DuckDB 1.5.5. The combined prediction file has SHA-256 `f0eb605ec1998262c2b2d6071b8e866a46bd744788abcff076255aab6de21d1a`.
