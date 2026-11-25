# PocketMD evidence review across eight uploaded trials

The review covers 261 numbered initial-entry criteria plus 11 distinct open-label extension criteria. Each of the 272 entries includes its source location, screening logic, evidence requirements, patient-scoped candidate queries and remaining conditions. The original archived protocol bytes were checked against all eight SHA-256 fingerprints. Full parent criteria are counted once. Cohort alternatives, lab predicates and appendix requirements remain attached to their parents.

## What can run

| Uploaded study | Numbered criteria | Tested criterion evaluator | Tested evaluator with specific holds | Only some predicates tested | Evidence specification only |
|---|---:|---:|---:|---:|---:|
| SOTIO 106S01 | 42 | 14 | 1 | 0 | 27 |
| NEOK001-1 | 38 | 1 | 2 | 0 | 35 |
| Recursion REC-1245-101 | 31 | 1 | 2 | 1 | 27 |
| Michigan NCT05653388 | 3 | 2 | 1 | 0 | 0 |
| Parabilis FOG-001-301 | 45 | 2 | 0 | 0 | 43 |
| DualityBio DB-1311-O-1001 | 42 | 3 | 0 | 1 | 38 |
| Philogen PH-L19TNFDOX2, historical v6 | 43 | 5 | 0 | 2 | 36 |
| Boehringer 1479-0032, NSCLC | 28 | 3 | 0 | 0 | 25 |
| **Total** | **272** | **31** | **6** | **4** | **231** |

The first two execution columns total 37. An evaluator may still require a signed judgment or abstain on missing or conflicting patient evidence. “With specific holds” identifies six with separately recorded authoring or branch limits. A study-wide version hold applies to Philogen even for criteria with a tested evaluator. The 235 in the last two columns require additional full-rule engineering or clinical source resolution before complete evaluation. No hospital feed, local-code crosswalk, clinical validation or live eligibility decision is represented by these counts.

## Inspect the evidence

- Open **evidence_register.csv** for one searchable row per criterion. **studies/** retains full structured logic, provenance and trial-specific context. REC also retains individual predicate contracts and supplemental requirements.
- **retrieval_plans.json** lists sample requests for synthetic patient SYN-001, separate reference-only resources and study-state dependencies. **coverage.json** identifies the concrete evaluator or tested parts. A candidate search can be broad. Binding still requires the right clinical concept, patient, episode, timestamp, method and source.
- **ACTION_REQUIRED.md** identifies the missing Philogen protocol and gives decision-changing examples of when to seek a governing interpretation. A lookup can return an empty patient record while a study question remains open independently.
- **verification.json** records each synthetic expected and actual result. The Michigan fixture replay overlaps prior regression coverage. These are engineering checks without independently adjudicated patient records.

## Reproduce

Use Python 3.10 or above with the `cryptography` package (tested with 50.0.0). Run from this directory. The listed runs are local and need no model key, hospital connection or live data.

```sh
python -B verify_release.py
python -B verify_release.py --source-dir "/directory/containing/original-uploaded-zips"
```

### From an eligibility clause to its patient evidence

DualityBio I06 requires a qualifying baseline LVEF measurement. The implementation verifies the measurement method, the protocol enrollment milestone, timing and versioned sources. Use the same synthetic bundle for retrieval and then criterion evaluation.

```sh
python modules/retrieve.py plan --study studies/DB-1311-O-1001.json --criterion I06 --patient synthetic
python modules/quantitative.py --example --study DB-1311-O-1001 --criterion I06 > demo.json
python modules/retrieve.py retrieve --study studies/DB-1311-O-1001.json --criterion I06 --patient synthetic --bundle demo.json --as-of 2025-03-05T12:00:00Z
python modules/quantitative.py --study DB-1311-O-1001 --criterion I06 --bundle demo.json --patient synthetic --as-of 2025-03-05T12:00:00Z --site-zone UTC
```

The final command returns MET for the supplied example. The catalogued search paths can also be used to design a site adapter. Actual FHIR server capabilities, pagination, local vocabulary and version availability must be confirmed on that deployment.

### Other executable examples

```sh
python prior_runtime/michigan.pyz --demo order-only --trace
python modules/assertions.py --example REC-1245-101 I11 > response.json
python modules/assertions.py response.json
python modules/duality_qtc.py --example > ecg.json
python modules/duality_qtc.py ecg.json
```

The Michigan example returns a criterion-authoring hold on the treatment order. The Recursion example uses a synthetic signed willingness and ability response. DualityBio E05 uses a patient-linked baseline QTcF series. Several modules use different research normalization profiles and command-line entry points. Those signatures are documented in the module docstrings. The research scripts do not form a single hospital-deployed matching service.

## Evidence standardization and remaining engineering

Preserve the originating hospital coding, version and source record. Bind a standard measurement, disease or drug only at the scope supported by that record. A drug order and a completed administration represent different events. A diagnosis and a metastasis assessment must refer to the relevant cancer episode. Retain the specimen, method, units, reference limit and clinical timestamp on a lab. The retrieval planner keeps non-patient site requirements separate.

REC I08 is a concrete partial result. Sixteen numeric predicates were tested, including branches that depend on a specimen, a local upper limit or a renal formula. Its parent needs the remaining predicates, branch composition and full-criterion fixtures. Philogen I02/E04 and DualityBio I17 have tested identity predicates. Their other clinical obligations remain visible in the source-mapped entries. Site-scoped permissions and protocol interpretations require their own versioned records. No patient model expansion was assumed for the review.

The reference for the candidate FHIR R4 query syntax is the [HL7 R4 search parameter registry](https://hl7.org/fhir/R4/searchparameter-registry.html). Code-system candidates and site-specific normalized event or form IDs have distinct scopes. Synthetic identifiers in the evaluators are research fixtures.
