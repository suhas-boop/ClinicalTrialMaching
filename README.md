# PocketMD TrialGPT R14

Start with [R14 results and reproduction instructions](nih_benchmark/round14/README.md) or open [the 91-case scorecard](nih_benchmark/round14/results/91_case_scorecard.csv). The command `python -B pocketmd.py trialgpt-evaluate` runs the current evaluation. The material below records earlier releases.

# PocketMD R13 · TrialGPT abstention audit

Start with nih_benchmark/round13/85_case_audit.csv and nih_benchmark/round13/README.md. Run python pocketmd.py audit-abstentions to reproduce all 134 predictions from raw notes. The sections below document historical releases.

# PocketMD R12 · Clinical note extraction

Provide a single-patient UTF-8 text note and patient identifier. The local extractor recognizes explicit clinical assertions and measurements, resolves supported negation and report context, and produces FHIR R4 resources linked to the original note. The deterministic matcher consumes the same typed evidence catalog as R11. This is a bounded vocabulary and grammar with documented abstentions. No model service or retrieval index is required.

## Try a note

Run from the extracted release root using Python 3.11 or later.

```sh
python pocketmd.py fhir-convert /tmp/demo.json --note nih_benchmark/round12/example_note.txt --patient demo
python pocketmd.py fhir-screen --bundle /tmp/demo.json --study NCT02219360 --criterion 435 --subject Patient/demo
```

The example explicitly documents a pulmonary embolism on chest CT. Criterion 435 is an exclusion and returns NOT_MET with the CT sentence and the matching Observation. A chest radiograph uses a different imaging modality. A planned test supplies no imaging result. The single-note command takes one presentation and one patient. Use a separate patient identifier or isolated snapshot for each demo. Longitudinal record merging, hospital-specific author verification and deployment are outside this release.

## Verify the findings

```sh
python pocketmd.py fhir-replay
python nih_benchmark/round12/check.py
python nih_benchmark/round12/raw_audit.py
python nih_benchmark/round12/test_pipeline.py
```

The 134 patient–criterion assignments, rule definitions and physician labels are the original TrialGPT evaluation set. The public extract contains 53 case narratives overall, including one group. Eligibility prediction uses no physician labels. The raw-note evaluation omits the per-patient reviewed chart entries and retains the group-source hold for the group vignette. Across all 134 pairs, its outcomes exactly reproduced R11. Six criterion decisions had source-backed MET or NOT_MET outcomes; all six agreed with physician labels. Physicians made 91 definite judgments. Insufficient evidence remained the primary disposition for 93 pairs overall.

The raw reader recovered 15/15 measured values and 7/7 current medications on the specified source-reviewed reference subset. Exact comparison includes patient, sentence, concept, value and unit or medication status. After the initial 2/7 medication result, the intake grammar was expanded to cover additional explicit current-use phrasings. Those reference cases informed development and cannot measure prospective accuracy. The other numbers on the chart and the inactive or uncertain medications were outside this measurement subset.

When applied in addition to existing chart intake, the reader added nine source-linked Observations across six charts. These include newly structured negations and an already documented admission represented as a Boolean the matcher can consume. No criterion changed disposition. Full references and source text are in `nih_benchmark/round12/results/added_evidence.csv`.

The authored wording checks passed 44/44. In a separate 20-example challenge, the initial run passed 16/20. The four omissions concerned an alternate CT sentence, arterial PaCO2, breastfeeding and Fitzpatrick phototype. Revised parsing passed 20/20 on replay. These are development checks, not an independent clinical validation. Original misses and final outputs are both supplied in the results directory.

## Implementation and boundaries

`prose.py` parses subject, clinical section and assertion with an existing field dictionary. `record_facts.py` handles explicit medications, diagnoses, measurements and symptom polarity. `intake.py` writes patient and source-document references, source-linked facts, and Provenance with original line numbers and Unicode character offsets. A missing supported fact continues to mean that the supplied material did not yield verified evidence. Other facts, free paraphrases or ambiguous references can remain unread. Scope includes selected note forms only; most complex screening windows and multi-event relationships still require separately verified inputs.

The full FHIR replay, raw-only comparison, wording tests, and official R4 schema validation receipt are under `nih_benchmark/round12/`. Earlier test results below describe versioned comparisons.

## Earlier releases

# PocketMD R11 · TrialGPT chart mappings

The R10 benchmark reached 84 record contracts without a native FHIR reader. R11 adds an explicitly scoped intake field and FHIR selector for each, retaining the prior trial rules and reference labels. The compiler and patient converter share the field definitions in `nih_benchmark/round9/clinical_fields.py`. For 29 contracts the converter also accepts tested, narrowly specified narrative forms. The remaining 55 use explicitly documented report fields. Broad narrative extraction, hospital feed coverage and independent clinical adjudication have not been validated.

## Run from this directory

```sh
python pocketmd.py fhir-compile nih_benchmark/round11/compiled.json
python pocketmd.py fhir-convert /tmp/pocketmd-new-chart
python pocketmd.py fhir-replay /tmp/pocketmd-new-chart
python nih_benchmark/round11/check_mappings.py
python nih_benchmark/round11/test_catalog.py
```

Use an empty directory for conversion. A single case can be screened with `python pocketmd.py fhir-screen --study NCT00827463 --criterion 795 --subject Patient/sigir-201514`. The default chart and the rebuilt benchmark chart give identical outcomes. The clinician labels enter scoring after all predictions have been generated.

## What the result means

All 58 formerly blocked pairs now reach MISSING_DATA and all 84 formerly unbound facts return no verified value from the original chart. All 53 benchmark bundles rebuild identically with the baseline conversion timestamp. The original six evidence-backed decisions were preserved, all six agreed with the physician reference, and coverage remains 6/91 physician-definite pairs. The unchanged catalog entries outside these active cases include 11 unsupported record contracts. Other studies and hospital interfaces require their own verified mappings.

The native matcher checks source patient, source digest, sentence provenance, typed result, and evidence scope. Study-specific fields require the matching study identity. A source sentence such as “The current chest CT shows pulmonary thromboembolism.” creates a scoped observation with the original sentence reference. A chest radiograph cannot supply that CT finding. For structured clinical notes, the supported notation is “section / field: value”. Values and units are checked. Numeric INR and arterial PaCO2 selectors also accept the verified standard coding without a local code inside this scoped source profile. A reviewed antifungal duration refers to the entire qualifying single-agent course immediately before randomization for the index episode; computing arbitrary multi-agent courses from administrations remains a separate integration.

Each row in `nih_benchmark/round11/results/resolved_mappings.csv` includes the affected criterion, expected field, supported source format, actual result, vignette and a brief retrospective chart review. That review is not read during inference. One issue found during review is the wording of the pregnancy branch for annotation 322. The benchmark replay preserved the frozen rule. The comparator CSV and full decision traces are in the same results directory.

The test receipt records 182 value checks, 273 uncertainty and scope checks, 58 wrong-study checks, four standardized-code and unit checks, four near misses on original charts and 12 full-rule controls. Separately, the seven catalog, nine FHIR and 189 workbench regression tests passed. Synthetic control evidence never enters a benchmark chart.

Terminology references: LOINC [6301-6](https://loinc.org/6301-6/) and [2019-8](https://loinc.org/2019-8/).

## Previous releases

# PocketMD R10 · Shared evidence mappings for TrialGPT

The TrialGPT rule compiler publishes one versioned catalog. A rule references each required fact by a hash of its clinical scope, value type, unit and responsible role. The native chart matcher uses the selectors attached to that exact contract. The normalized-packet screener reads the same compiled rule pack and retains its protocol, encounter and signer checks. This implementation covers the TrialGPT benchmark chart profile. The eight sarcoma study adapters remain separately versioned.

## Run

Use Python 3.11+ from the extracted directory.

```sh
python pocketmd.py fhir-compile nih_benchmark/round10/compiled.json
python pocketmd.py fhir-replay
python pocketmd.py fhir-screen --subject Patient/sigir-20146 --study NCT02512159 --criterion 116
python nih_benchmark/round10/test_catalog.py -v
```

The replay accepts a chart export directory as its positional argument and an optional `--out` for results. Regenerate a chart with `python pocketmd.py fhir-convert NEW_DIRECTORY`. A single-subject screen uses the same catalog, reader and deterministic evaluator as the replay. Prior normalized-packet callers can use `trialgpt-screen` with their existing arguments.

## Results

| Measure | R9 | R10 |
|---|---:|---:|
| Criterion–patient pairs | 134 | 134 |
| Evidence-backed definite decisions | 6 | 6 |
| Agreement among definite decisions | 6/6 | 6/6 |
| Primary missing-data dispositions | 93 | 35 |
| Primary engineering mapping holds | 0 | 58 |
| Distinct record retrieval requests | 155 | 71 |
| Exact benchmark state matches | 38 | 14 |

The benchmark has no engineering-hold label. Twenty-four pairs previously agreed on insufficient information and now carry a more specific internal reason. Every change in primary disposition was from missing data to a mapping hold. The engine can request evidence for a supported branch and a mapping for another branch of the same rule. Counts of requests are separate from counts of criteria.

The compiler emitted 186 distinct contracts. Of 172 patient-record contracts, 77 have a native chart selector and 95 lack one. The remaining 14 require evidence from the study team, investigator or patient. The replay reached 84 distinct unsupported contracts. Each appears in `nih_benchmark/round10/results/engineering_mappings.csv` with affected annotation IDs. A mapping hold routes to engineering. Missing evidence for an implemented selector routes to record retrieval. Role-based requests continue to use their existing destinations.

The native reader verifies the chart subject, source document digest, converter provenance, source sentence and registered evidence context. Quantitative readings also require the selected local and LOINC codes and the specified UCUM unit. Rule validation and explicit assertion polarity are preserved. This package supports the local TrialGPT chart profile; a hospital feed needs validated mappings to its native codes and provenance conventions.

## Verification and traces

`nih_benchmark/round10/compiled.json` contains both rules and selectors. The case comparison is in `results/matching.csv` under the same directory. `traces.json` records the selected contract, evidence and requests; `summary.json` records the score and release fingerprints. Reference labels enter scoring after prediction.

All 53 original FHIR bundles reproduced byte-for-byte with the original conversion timestamp. The same 134 outcomes reproduced from the rebuilt chart. In a controlled end-to-end check, explicitly documenting an ulcer caused by a burn produced NOT_MET; explicitly negating that cause produced MET. The original case stayed MISSING_DATA. An unchanged threshold gave NOT_MET at 89/min and MET at 90/min. Patient identity, scope, provenance, conflicting observations and missing mappings have targeted regression tests. These controls supplement the benchmark; they do not increase its decision count.

---
## Previous releases and archived results

# PocketMD R9 • TrialGPT patient chart in FHIR R4

The complete set of 53 distinct case narratives from the NIH TrialGPT criterion annotation dataset is included. There are 52 individuals and one group of 14 people. Every original note is recoverable byte-for-byte from DocumentReference.content. A stable identifier ties each note and its derived resources to the original case. No dates of birth, trial enrollment dates, medication administrations, or individual identities were inferred from group text.

## Use the chart

From the extracted release root, using Python 3.11+:

```sh
python pocketmd.py fhir-serve --port 8765
```

In a second terminal:

```sh
curl 'http://127.0.0.1:8765/fhir/metadata'
curl 'http://127.0.0.1:8765/fhir/Observation?patient=sigir-201418&code=http%3A%2F%2Floinc.org%7C8867-4'
curl 'http://127.0.0.1:8765/fhir/MedicationStatement?patient=sigir-20147&medication=42351'
```

The heart-rate query returns one observation of 141/min from sentence 2 of the infant's vignette. The medication query returns the stated current use of lithium carbonate. The drug record makes no assertion about dose or administration. The equivalent offline command for the first query is:

```sh
python pocketmd.py fhir-query --subject Patient/sigir-201418 --type Observation --code 'http://loinc.org|8867-4'
```

The local server supports resource reads and the listed search parameters in its CapabilityStatement. The SQLite database holds the actual exported FHIR JSON. Each self-contained transaction Bundle uses PUT with stable IDs for loading into a compatible write-enabled FHIR server. Per-type NDJSON files contain each unique resource once. The export folder is `nih_benchmark/round9/export`. No upload to an external EMR has been performed.

## Data and provenance

The converter combines reusable extraction for explicit assertions, age and blood pressure with source-reviewed annotations for the supplied vignettes. The latter are pinned to a note digest and checked against their quoted source sentences. This is a dataset conversion, with a limited reusable automatic reader. Converting other clinical corpora with the same semantic coverage requires additional extraction or review. Trial identifiers, published outcomes and physician annotations are excluded from conversion inputs.

There are **477 structured findings and events**, each with a Provenance record pointing to its source document and numbered sentence(s). Clinical classes include 423 Observations, 31 Conditions, 11 Procedures, 9 MedicationStatements and 3 FamilyMemberHistory resources. A reported intention to consent is a prospective statement. A family member's procedure and a patient's own procedure are distinct. Negative and qualitative findings are kept at the scope of their source. Relative time and attribution appear in the local evidence-context extension. Provenance.recorded is conversion time. No archival narrative was assigned a calendar screening date. Administrative gender is left unspecified where the vignette only describes a person in prose.

At least one structured item links to 321 of 326 original sentences. The five other sentences are retained in the source documents: four belong to the group vignette, and one describes both siblings' current wellbeing. Sentence coverage does not establish extraction of every clinical detail in a sentence. Local codes remain available for qualified findings without a verified standard equivalent. Numeric readings record UCUM units when available; a unitless source remains unitless. The export includes selected LOINC measurements, ICD-10-CM disease codes and RxNorm ingredients, with the local vocabulary alongside them.

Files of interest:

- `bundles/` and `ndjson/` hold interoperable FHIR resources.
- `chart.sqlite` is the queryable store.
- `source_links.json` and `sentence_coverage.csv` trace resources back to original material.
- `matching.csv` and `matching_traces.json` show criterion outcomes and evidence resource IDs.
- `conversion.json`, `validation.json` and `matching_summary.json` give measured totals.

## Evaluation

All 53 bundles and 1,061 unique resources passed the HL7 FHIR 4.0.1 JSON schema checks. All 2,424 within-bundle resource-reference occurrences resolved, and the index and NDJSON contents agreed with the bundles. These checks cover schema and local referential integrity. Implementation-guide conformance and site-specific interoperability require separate validation.

Matching used the frozen R8 rules on the 134 publisher evaluation assignments. The matching process obtained facts from the on-disk patient-scoped FHIR resources, checked source links and units, and sealed its outputs before joining physician outcomes. An explicit numeric value or an admitted same-scope fact can drive a decision. Additional narrative findings and historical events are discoverable even if a released trial lacks a corresponding approved mapping. No RAG or LLM call is required for lookup or screening. Six criteria returned MET, and none returned NOT_MET. All six agreed with the physician label. The 128 other outcomes and the clinician question queue were unchanged. This replay checks preservation of matching behavior on development data.

## Reproduce

```sh
python pocketmd.py fhir-convert fresh-export
python pocketmd.py fhir-replay fresh-export
python nih_benchmark/round9/validate_export.py fresh-export
python nih_benchmark/round9/test_fhir.py
python pocketmd.py test
```

The validation command uses the Python package jsonschema and the included official R4 schema ZIP. Normal queries and screening use the Python standard library. To reproduce the original provenance timestamps, pass the recorded conversion instant from conversion.json to the converter using --recorded.

Sources: https://huggingface.co/datasets/ncbi/TrialGPT-Criterion-Annotations • https://hl7.org/fhir/R4/ • https://hl7.org/fhir/R4/fhir.schema.json.zip • https://loinc.org/ • https://rxnav.nlm.nih.gov/REST/ • https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search


# PocketMD R8 • TrialGPT criterion-level evaluation

**Scope.** Every one of the 134 records flagged `training=false` in the NIH TrialGPT criterion annotation release is accounted for. There are 134 distinct study–polarity–criterion combinations, 44 patient narratives and 68 studies. There are also 881 training rows in the publisher file. These are outside the evaluation denominator and have not been newly authored as a training library. This is a development replay of patients previously examined in PocketMD. The registry context is a dated public reference and cannot establish that the site used the same protocol amendment.

## Results

| Rule readiness | Criteria |
|---|---:|
| Executable on the normalized patient evidence model | 116 |
| Clinical or protocol definition required | 18 |
| Total | 134 |

| Patient outcome on the original vignette | Criteria |
|---|---:|
| MET with source evidence | 6 |
| NOT_MET with source evidence | 0 |
| Missing sufficient verified record evidence | 93 |
| Protocol definition pending | 18 |
| Investigator assessment | 6 |
| Study-team data | 2 |
| Patient response | 2 |
| Resolve the individual in one group narrative | 7 |

All six definite calls agreed with the physician consensus. The consensus was definite on 91 rows, so coverage was 6/91. Five of the six used at least one physician-cited sentence. The previous mixed automated/abstracted replay had nine definite calls. R8 reopened criterion 20 (general compliance does not document travel access), 142 (a study-personnel determination was required), and 212 (a future consent statement does not establish disposition of written consent). The comparison is within the same development cohort. The two modes differ in their permitted evidence. No claim of improved accuracy or deployment readiness follows from the lower coverage.

## Distinct actions

The clinician protocol queue contains 18 questions with criterion, trial and a pinned registry reference. Separately, the patient-screening queue contains eight distinct investigator assessments, three patient responses, three study-team requests and one subject-identity request. It also contains 155 distinct scoped evidence lookups. A case may require multiple inputs. The archive and research notes cannot answer all of them. The clinical review CSV has answer and governing-section fields for the reviewer. An answer to a definition question must be incorporated into a new rule version and tested before use. A signed patient-specific assessment can enter through the existing authorized FHIR evidence route.

## Engineering loop

1. Verified exact publisher membership using a hash of ordered annotation ID, patient, trial, polarity, criterion and full note. Retained the historical R7 data and rule packs.
2. Reviewed the existing typed rules, retrieved registry context for targeted ambiguities, compiled 116 normalized rules, and recorded 18 specific interpretation questions. Resolved the French-language scope in its pregnancy-study context. Changed the prognosis threshold to a typed comparison, staffed by an investigator, and the antifungal duration to a threshold on a scoped course. This latter contract requires a trusted measurement of the qualifying course for the index indication and time anchor. Raw prescriptions do not establish administration.
3. Applied direct patient-scoped lookup. The vignette adapter writes versioned observations with exact source sentences. A shared concept dictionary distinguishes history from current assertions, ignores hypothetical and family statements, and withholds conflicts it detects. The benchmark visit date/episode, record author, local codes and FHIR metadata are simulation infrastructure. Source text is real benchmark input. Study-version fingerprints identify this research rule bundle.
4. Tested all executable rules on qualifying, failing and empty normalized packets, plus applicability gates when present. Ran 368 readiness controls across all 134 rows, and 656 additional mixed-input checks against a separate Boolean evaluator. Both synthetic label directions required provenance. For the group vignette, the screening entry point withholds patient decisions even if the packet contains a numeric value. A signed synthetic prognosis arriving later changes the state automatically and redelivery is idempotent. Tests also reject evidence against the wrong person or author.
5. Sealed predictions before joining the publisher's physician labels in this replay. Source hashes, case-level results, mixed-branch checks, changes from R7 and synthetic vs actual evidence are available under `nih_benchmark/round8/results`.

## Where patient extraction stands

All 116 rules have a query path against typed, versioned patient facts. The native TrialGPT notes contain prose. Of 186 local evidence contracts, 74 have a direct note reader for at least one supported phrasing. Of the 116 rules, 37 have reader support for every required fact type, 18 have partial support, and 61 depend entirely on upstream normalized inputs. A supported phrasing does not guarantee a given note documents the fact. Conversely, a missing result cannot prove a fact was absent from the source record. The code never imputes a negative from omission. Evidence-catalog rows show the typed field, scope, owner, unit and whether a note reader exists. The semantic authoring work here used source-reviewed rules; this run does not validate a fully automatic authoring model, free-form hospital text extractor or live EMR connection. No RAG or model calls were used in the scoring path.

## Run

Using Python 3.11+, from the release root:

```sh
python nih_benchmark/round8/run.py
python nih_benchmark/round8/verify.py
python -m pip install duckdb
python nih_benchmark/round8/score.py nih_benchmark/round8/publisher/annotations.parquet
python nih_benchmark/round8/report.py
python pocketmd.py test
python pocketmd.py trialgpt-screen --study NCT01207128 --criterion 957 --packet nih_benchmark/round8/example_packet.json
```

The last example returns the outstanding patient-specific prognosis assessment. To reevaluate with new normalized evidence, import a trusted, versioned FHIR archive using `pocketmd.py records import-bundle`, then supply its SQLite index to the same `trialgpt-screen` command with `--index`. The rule fingerprint, patient, encounter, episode, author role and as-of cutoff must match. All exported screening packets and original public note contexts are available for inspection. The source is https://huggingface.co/datasets/ncbi/TrialGPT-Criterion-Annotations.

# PocketMD R7 • Patient record retrieval

A missing evidence request now drives a patient-scoped document search and a replay of the same versioned rule. The response carries the original state, ranked passages, document identity and locator, any verified fact references, the recomputed state, and the remaining evidence requests. Clinical outcomes come from the existing typed evaluator. Searches work on local authorized archives. Live OncoEMR access has not been exercised.

## Run the included example

Requires Python 3.11+ with SQLite FTS5. PDF attachment hydration additionally uses the Python package pypdf. The example files are synthetic. From the release root run:

```sh
d=nih_benchmark/round4/example
python pocketmd.py records import-bundle --index demo.sqlite "$d/archive.json"
python pocketmd.py records screen --index demo.sqlite --packet "$d/packet.json" --rules "$d/rules.json" --study NCT02512159 --version aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
```

The retrieved wound record changes criterion 116 from MISSING_DATA to NOT_MET. Criterion 115 still needs evidence about a different cause. Dedicated numeric screening-vitals documents are covered by separate threshold, conflict, provenance and timing tests.

## Search an authorized chart export

```sh
python pocketmd.py records import-export --index chart.sqlite patient-export.json --missing-manifest missing-attachments.json
python pocketmd.py records search --index chart.sqlite --patient Patient/EXAMPLE --as-of 2026-11-23T12:00:00Z --query "transfusion"
```

Use the actual subject and cutoff from the screening task. Search results include linked report references and page/line locators. The importer associates extracted text with the original report through clinic, case, subject and source reference. It indexes final, amended, corrected or appended report text as searchable. Requests that explicitly seek prior history can retrieve candidate records from an earlier encounter. A missing encounter or episode association permits a candidate for inspection. Executable evidence requires the contract's scope checks. The index, original bytes and missing-attachment manifest contain private information and belong in the authorized local environment.

The manifest identifies the missing original for each current source row, including its export ID, report reference and SHA-256. Retrieve originals through the authorized chart system and place each file under its exact SHA-256 filename. The importer verifies the bytes before reading PDF text or UTF-8 plain text. A scanned PDF without extractable text remains on the request list. A hash mismatch rejects the import. Use the actual retrieval time:

```sh
python pocketmd.py records import-export --index chart.sqlite patient-export.json --attachment-dir originals --available-at "$RETRIEVED_AT" --missing-manifest still-missing.json
```

The importer stores local immutable versions. Record withdrawal requires a revised source status. A missed delivery or omission from a later partial export cannot certify deletion. Queries cannot read an original recovered after the specified cutoff. Use a separate index per source namespace when FHIR IDs could collide across systems. Re-run the screen command when new evidence arrives. Binary attachment fetching, OCR, identity reconciliation across systems, and free-text clinical adjudication remain outside this release.

## What the replay established

| Measure | Result |
|---|---:|
| TrialGPT audit stratum | 63 criterion–patient pairs, 29 patients |
| Public texts | 87, comprising one numbered vignette and two original topic text fields per patient |
| Rows with a keyword or clinical synonym hit | 29/63 |
| At least one physician-cited sentence in top 5, unexpanded query | 10/24 |
| At least one physician-cited sentence in top 5, with clinical synonyms | 17/24 |
| New evidence-backed MET or NOT_MET | 0/63 |
| Current, searchable documents in two separate supplied exports | 80/98 |
| Current attachments requested by exact fingerprint | 18 |
| Additional document rows held by report-status checks | 42 |

Each public query used the active missing-fact scopes from the evaluator. The 24-case denominator includes only rows with physician sentence annotations. Citation overlap measures retrieval on previously reviewed development data. Candidate passages can mention related conditions or procedures without establishing the required facts. The original public case summaries are alternative representations of the same cases, with no underlying full patient chart supplied. The two uploaded patient exports were evaluated separately. Chart search yielded 10 mentions across eight documents for the transfusion query in export 2. Those are retrospective leads. Treatment status, date and trial window still require verification.

```sh
python nih_benchmark/round7/replay.py
python nih_benchmark/round7/chart_inventory.py export-A.json export-B.json
python pocketmd.py test
python pocketmd.py verify-studies
python pocketmd.py verify-medication
```

The per-criterion CSV records the query, case, top source and location, citation overlap and before/after state. The receipt includes the hash of results before joining physician sentence annotations. Source XML versions are pinned against the earlier recovery receipt. The topics came from https://www.trec-cds.org/topics2014.xml and https://trec.nist.gov/data/clinical/topics-2015-A.xml. Aggregate checks are in `verification/r7-*`. Previous implementation notes follow.

# PocketMD R6 hematology replay

Use `python pocketmd.py screen-lab chart.ndjson --patient Patient/example --screening-day 2021-05-11 --simulate-c1d1-plus-seven --use-export-unit-aliases --hematology`. Use `--as-of` to change the review cutoff. The documented C1D1 option and the platelet-only interface are preserved. The hematology option evaluates the full released DualityBio I07 expression with evidence for platelet count, blood hemoglobin mass concentration and absolute neutrophil count. The thresholds come from the pinned release. LOINC 718-7 and 26499-4 identify the new analytes. Absolute neutrophil percentages, mean corpuscular hemoglobin, and an isolated microliter unit cannot satisfy those contracts. Output includes all candidate values and content-hashed native report and observation references.

## How repeat results are handled

A review of the exact v6 protocol PDF (SHA-256 `1c20138b1b1d0cf2e9f071154cfbfeb71d3bc7a5857881810c9a0ece7ba21c67`) covered §5.1 item 7, the schedule of activities Table 1 note 17, §5.4, §8.2.4 and §10.2.1. The schedule distinguishes screening labs and C1D1 labs. The latter may reuse recent screening labs under the stated conditions. The statistical section selects a baseline for analysis. Section 5.4 describes a new, sponsor-approved rescreen after screen failure. We found no general instruction selecting the most recent draw for I07 screening eligibility.

For a top-level required lower-bound comparison, all independently verified candidate values can establish the same Boolean outcome. The program retains every supporting reading and evaluates the full criterion at both ends of each resolved interval. Clinical measurement choice remains open when candidates cross a threshold. In that case the engine routes one protocol-version-specific question if the overall criterion still depends on it. Invalid units, broken source links, mixed identity or unverifiable records still prevent binding. This logic does not substitute for checking whether the specimen, visit, treatment-support history or patient actually satisfies the protocol.

## Replay

`python experiments/hematology/replay.py export-A.ndjson export-B.ndjson` reproduces aggregate results. The cohort uses the same 37 platelet-observation dates from the same two supplied exports as R5. Selection was conditioned on data availability. Counts are repeated research scenarios, not independent patients or estimates of clinical accuracy.

| Full I07 determinations | R5 | R6 |
|---|---:|---:|
| Available context without supplied trial anchor | 0 | 0 |
| Simulated screening date | 10 | 13 |
| Two-day follow-up under same simulated C1D1 | 16 | 26 |

Every full determination was NOT_MET. In one newly resolved scenario, hemoglobin was 8.3 g/dL against the 9 g/dL threshold. At follow-up the eight platelet comparisons previously blocked by different values yielded two MET and six NOT_MET. No repeat-selection question remained in this cohort. For the 11 open scenarios, seven had final report-linked candidate codes for albumin, AST, ALT and total bilirubin. Code presence alone does not verify specimen, value units, lab-specific upper limits, or all I07 conditions. The probe found no final report-linked INR using the specified standard code on those 11 dates. Other codes or chart documents may carry additional information.

Engineering receipts are in `verification/r6-cohort.json`, `verification/r6-tests.txt`, and the two other R6 verification files. The TrialGPT score remains the previously measured 9/91 physician-definite cases. This release adds a native FHIR lab pathway and makes no new benchmark accuracy claim. The R5 study and earlier receipts follow.

# PocketMD native lab screening (R5)

This release carries a native hospital platelet result to the released DualityBio DB-1311-O-1001 I07 rule. The original rule supplies the comparison and all other obligations. The same catalog entry used by retrieval is returned as the evidence requirement, including the released fact fingerprint, clinical code, accepted units, source fields and timing anchor. A clause may pass even when the whole criterion still needs evidence. This release covers one native analyte and one trial criterion.

## Run

Python 3.11+. Set the patient reference from the same export and an explicit screening day.

```sh
python pocketmd.py screen-lab chart.ndjson --patient Patient/example --screening-day 2021-05-11
python pocketmd.py screen-lab chart.ndjson --patient Patient/example --screening-day 2021-05-11 --simulate-c1d1-plus-seven --use-export-unit-aliases
python pocketmd.py screen-lab chart.ndjson --patient Patient/example --screening-day 2021-05-11 --simulate-c1d1-plus-seven --use-export-unit-aliases --as-of 2021-05-13T23:59:59Z
```

For trusted documented timing, use `--anchor-packet trusted-encounter.json --as-of TIMESTAMP` instead of the simulated date flag. The supplied packet contains the patient's study-tagged FHIR screening encounter and a versioned C1D1 order or completed study-drug administration under the existing DualityBio event mapping. It must pin the protocol fingerprint in its context and agree on patient, screening date and cutoff. A planned order remains labeled planned. Testing covered both a synthetic documented order and a synthetic completed administration. Neither uploaded chart supplied the normalized first-dose marker. The new adapter does not infer that a routine oncology visit was a trial screening encounter.

The implemented blood platelet mapping requires LOINC 26515-7 and a compatible UCUM quantity. It treats the analyte's coded blood system as specimen-type evidence in this research export; an explicit specimen reference needs verification and currently produces a hold. The opt-in, exact export alias `Thousand/uL` is an engineering crosswalk for these files. Each accepted result has two content-hashed resource references. Original FHIR resources without version IDs retain their source identity through the content hash. The native resources come from a trusted caller-supplied snapshot. No live FHIR server, signature verification, PDF attachment parsing, or automatic patient identity matching was exercised. The archive supports one unambiguous resource version per logical identity for this native path.

## Results

Both supplied exports were evaluated on every date with a platelet observation (37 screening-date scenarios, two patients). Tests use UTC. The event date is simulated seven calendar days after each screening date. The screening-day cutoff is end of day, and follow-up uses the same assumed C1D1 with the cutoff advanced two days. The date-only simulation includes calendar days 1 through 7 before C1D1 and withholds same-day results of uncertain order. Reports issued after the cutoff cannot affect a result. The documented-anchor path additionally checks actual elapsed time and encounter, and withholds uncertain boundary cases. Different qualifying values remain unresolved pending a protocol-appropriate selection. These are overlapping retrospective scenarios selected by test availability.

| Metric | Screening-day cutoff | Two days later |
|---|---:|---:|
| Platelet meets threshold | 9 | 13 |
| Platelet below threshold | 10 | 16 |
| Platelet unresolved | 18 | 8 |
| Full I07 NOT_MET | 10 | 16 |
| Full I07 MISSING_DATA | 27 | 21 |

Without a supplied anchor all 37 remained open. With the hypothetical date, 13 previously open platelet clauses gained a definite answer on follow-up and three previously failing clauses reopened when another, different value became available. No full I07 pass occurred. The replay supplies platelet evidence alone. Independent contraindications, other labs and hematologic support history retain their own evidence requirements. An authentic date, purpose, provenance and clinical review are needed before applying these research findings to an enrollment decision. No confidence or population accuracy estimate follows from the replay.

## Feedback into the pipeline

For typed study packs the normal `screen` entry point now reports evidence-backed MET or NOT_MET decisions and distinct human, retrieval and engineering requests. Human roles follow the underlying rule. Counts use scoped task IDs. A new replay of the same snapshot does not create extra work. The numeric vignette adapter reads explicitly documented current-patient heart and respiratory rates from bounded measurement lines. A qualitative description yields no quantitative value. The rule author still uses the existing model-first path. The narrow reader handles chart evidence, not protocol interpretation.

All 71 earlier TrialGPT rows reproduced with the frozen assisted abstractions. All 63 later rows were rerun with the automatic reader. The total remains 9 definite agreements out of 91 physician-definite rows across 134 tested rows. On the last panel the engine produced 85 distinct record lookups and seven protocol questions. No new independent patient panel was used. The audit separately inspected the 14 outstanding missing-data rows with cited sentences and the four authoring holds. Public registry eligibility text was recovered for all four. No authoritative clarification was recorded. The 15 remaining rows with no physician-cited sentence received routing only. The 33-row audit proposes 27 record lookups at the criterion level, five protocol clarifications, and one investigator review if existing assessment records do not settle the issue. These are engineering recommendations, separate from automatically generated requests. The four public registry records and their hashes are in `nih_benchmark/round5`. No coordinator was contacted.

## Reproduce the evaluations

```sh
python nih_benchmark/round5/benchmark_audit.py
python nih_benchmark/round5/chart_replay.py export-A.ndjson export-B.ndjson
python pocketmd.py test
python pocketmd.py verify-studies
python pocketmd.py verify-medication
```

Use `--private-examples output.json` with the chart replay to retain exact source resources locally. The code distribution includes aggregate chart results only. The accompanying private evidence file holds original DiagnosticReport and Observation resource copies from the two supplied exports. The `verification/r5-*` files contain the test receipts. Prior revisions and benchmark limitations follow.

# PocketMD record retrieval and rescreening (R4)

A screening request can now read a second local collection of normalized FHIR records before returning the remaining evidence requests. The optional archive works with the six typed study packs. A historical version retains its version hold. The Michigan and SOTIO native evaluators report that archive recovery is unsupported when this option is supplied. Existing screening without an archive follows the prior release.

## Try it

From the extracted folder, run the following synthetic wound example. It uses the same two rule definitions as public annotations 115 and 116. The source is a test record. The dates, identifiers, roles and protocol fingerprint are fixture values.

```sh
cd nih_benchmark/round4/example
python ../../../pocketmd.py recover --rules rules.json --packet packet.json --archive archive.json --study NCT02512159 --version aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
```

Both criteria initially need evidence. The archive documents a burn and the burn exclusion returns NOT_MET with the versioned Observation and DocumentReference. The other exclusion continues to request evidence of an insect bite or leishmaniasis. An encounter with the burn diagnosis alone does not establish those separate facts.

For a released typed study, run `python pocketmd.py screen PACKET.json --archive ARCHIVE.json` from the release root. The packet supplies the pinned study context. An archive supplies a FHIR collection with normalized Observations and their version-linked DocumentReferences. The output retains all criterion dispositions, changed outcomes, supporting resource references, and the remaining scoped requests. Archive metadata cannot enable new mappings or authorize signers. The trusted calling application provides the original packet, site-specific grants, identity and authorized archive. The implementation reads a supplied export. Live hospital access, normalization of arbitrary hospital notes, and deciding when a human should be contacted after an unsuccessful lookup remain integration work.

## What was recovered from the public cases

In the earlier 49-row audit, 12 criteria had partial patient evidence. We compared all 12 to the original descriptions and summaries for their 10 TREC topics. The descriptions add no decisive detail. The available source material contains no linked scan, operative note, consent log, or other independent record resolving the missing qualifiers. We replayed the prior source-linked facts for all 12 with an empty supplemental chart. All 12 remained MISSING_DATA. The follow-up is an audit of an already inspected cohort.

The 12 rows give ten initial chart lookup bundles. The two ulcer exclusions share a wound assessment. The two surgical criteria share a surgical consultation/operative record. The lookup grouping in the CSV is manually reviewed for these specific episodes. The engine still evaluates each distinct criterion and preserves its requests. Ten lookups do not imply ten questions for clinicians.

See `nih_benchmark/round4/PocketMD_12_Source_Recovery.csv` for individual missing details, `public_replay.json` for executions, and `source_receipt.json` for input fingerprints. To reproduce the audit, download [2014 topics](https://www.trec-cds.org/topics2014.xml) and [2015 Task A topics](https://trec.nist.gov/data/clinical/topics-2015-A.xml), then run:

```sh
python nih_benchmark/round4/trace_sources.py --topics-2014 2014.xml --topics-2015 2015.xml --out replay
```

## Independent check of two uploaded FHIR exports

Run `python pocketmd.py chart-links path/to/fhir-resources.ndjson` to check native DiagnosticReport.result references. Export A contains 79 reports and 124 Observations. All 121 result references linked within the same subject. Export B contains 260 reports and 1,690 Observations. All 1,450 references linked within the same subject. Across both exports 199 reports contain result links and 140 contain a presented form. Zero Observations declare the screening profile consumed by this typed archive adapter. The native relationship supports retrieval. Clinical code, units, timestamps, role, provenance and criterion-specific scope still require a validated mapping for each fact. Existing specialized study mappers may handle individual facts independently. The distributed receipts contain aggregate counts only. These exports are separate from the public TREC cases.

## What the engineering tests establish

The new tests cover affirmative and explicitly negative source findings, unresolved sibling criteria, missing sources, wrong scope, unauthorized author, binding holds, duplicate delivery, amendments, future versions, retractions, disagreements, and identity/version collisions. The synthetic imaging case combines a pre-existing GCS result with a subsequently retrieved qualifying CT finding. The released 1479-0032 fixture changes I01 from MISSING_DATA to MET with supporting evidence. Run `python pocketmd.py test`, `python pocketmd.py verify-studies`, and `python pocketmd.py verify-medication`. Receipts are in `verification/r4-*`. These controls establish deterministic behavior under supplied inputs. New accuracy estimates require independently reviewed patient records with linked source documents.

# PocketMD external validation, third round

Run `python pocketmd.py vignette nih_benchmark/round3/example_input.json` to screen an NIH narrative with a reviewed rule. It extracts the age directly and cites the original sentence. Run `python pocketmd.py vignette-case nih_benchmark/round3/example_group.json` to see the eight-criterion group case produce one subject-identification request while preserving its independent trial wording question.

## What was audited

The 49 earlier physician-decided cases that remained open have a line-by-line engineering audit with the criterion, narrative, physician sentence IDs and rationale in `nih_benchmark/round3/prior_49_audit.csv`. These categories are engineering judgments, with one primary issue assigned to each case. They are not new physician labels. Twenty-four had no decisive chart statement, twelve had partial evidence, five had no single index patient, four needed a specific person's preference or judgment, three lacked governing protocol context, and one required clinical interpretation of a cluster of findings.

## What changed and what was tested

The vignette adapter automatically binds explicitly stated patient age in recognized presentation sentences. It requires the declared year units and the approved presentation-age scope. Trial date and patient presentation date are assumed coincident only in this research snapshot. The source reader detects selected explicit group introductions and can request the index patient once across criteria. It is deliberately narrow. It does not establish full automatic extraction, general subject resolution or clinical accuracy. The registry context tool verifies the study identifier, preserves the source fingerprint and distinguishes a current registry record from the protocol that governs a release.

The remaining 24 patients contribute 63 non-training rows across 37 trials. All were disjoint from both previous panels. Rules were authored in-session from criteria before examining the notes. The assisted arm used explicit sentence-backed abstractions. The new automatic arm received no patient abstractions. The combined arm ran both. All three decided the same four criteria, all age exclusions, correctly against the benchmark. Physicians decided 37 of 63. The other 59 algorithm outputs were 52 missing-data results and seven authoring holds. Exact cited-sentence sets matched on two of four automatic decisions, and one or more physician citations overlapped on three of four. All four had a cited age statement. The earlier group-case and context examples are development checks and did not contribute to this score. No fresh NIH non-training patients remain from this dataset selection. Subsequent changes need a new dataset or independently collected cases for prospective testing.

`python pocketmd.py retest` rebuilds blinded predictions. From the round3 directory, `sha256sum -c freeze.sha256` checks the frozen inputs, source adapter and predictions. `results.csv` and `summary.json` contain the score. To re-score, install DuckDB and run `python nih_benchmark/round3/score.py SOURCE_PARQUET`. The prior two rounds, original eight trial packs, and medication checks are retained below. On the audited dyspnea example the renal unit remained ambiguous in the registry, but the study's independently documented age range already placed the 30-year-old outside it. This separate study observation was not scored as a renal decision.

# PocketMD trial matching research pipeline

Start with `python pocketmd.py demo`. This replays criterion authoring, protocol clarification and patient screening with recorded model responses. See `nih_benchmark/summary.json` and `nih_benchmark/all_results.csv` for the external evaluation.

## Architecture

| Input | Processing | Output |
|---|---|---|
| One criterion, its inclusion/exclusion direction, governing passages, and a versioned evidence catalog | Author proposes a typed expression. Verification checks source obligations and bindings. Insufficient context opens a question. An attributed answer triggers another review. | Executable rule, protocol clarification, or engineering mapping gap |
| Patient evidence, clinical context and its source | Select by patient, episode, screening time, data type, unit, provenance and permitted role. Drug checks can require ingredient, formulation, administration, line and course. | Verified typed facts or a specific evidence gap |
| Released rules and a normalized FHIR packet | Deterministic evaluation checks applicability, thresholds, Boolean branches and completeness. | Criterion outcome and versioned supporting references |
| An unresolved typed rule | Retain facts already established, inspect only unresolved branches that can change the answer, assign the responsible role and combine duplicate requests within the same scope. | Record-retrieval tasks, engineering tasks, or distinct questions for the study team, investigator or patient |
| New chart evidence or an attributed protocol answer | Re-evaluate the dated packet or re-author the affected protocol version. Keep original inputs and results for comparison. | Revised result with supporting evidence |

## Running

Extract the archive. Use Python 3.11+ and install `pip install -r criterion_workbench/requirements.txt` for PDF intake and the full workbench tests. Core structured screening and public benchmark replay use the Python standard library.

- `python pocketmd.py studies --list` lists all eight uploaded study releases.
- `python pocketmd.py screen eight_rules/release/examples/1479-0032-met.json` uses the released study and returns criterion results and scoped requests. Six typed packs use the new review layer. Michigan and SOTIO keep their original evaluators and evidence traces. Philogen v6 remains historical only.
- `python pocketmd.py author --help` exposes trial authoring, clarification, and screening for the authoring workbench. Live calls require a separately configured model. Saved provider outputs make the demonstration reproducible offline. Authored age/ECOG expressions and the eight released study packs have different executable representations. They retain their own validators.
- `python pocketmd.py review --help` evaluates a custom, already-reviewed typed rule pack and normalized packet. Supply matching study and version identifiers. Production callers must authenticate those identifiers and configure approved mappings and signer roles.
- `python pocketmd.py benchmark` runs the frozen public rules and sentence-backed abstractions through the evidence review and FHIR evaluator. `python nih_benchmark/summarize.py` joins to the frozen results.
- `python pocketmd.py test`, `python pocketmd.py verify-studies`, and `python pocketmd.py verify-medication` run the workbench tests, the eight-study release verification, and the focused Michigan medication experiment.

## What changed after external feedback

In the first round 17 physician-decided exclusion rows with no cited sentence were held by PocketMD. We preserved the requirement for positive evidence of a qualifying or negative finding. The release now retains partial evidence when a whole criterion cannot be decided and separates record retrieval from questions requiring specific human roles. Typed criteria sharing an identical scoped requirement produce one request. Totals are distinct requests, not counts of patients or criteria. A criterion can produce several requests. Site and engineering tasks are separate from clinical outcomes.

## External benchmark

NIH TrialGPT Criterion Annotations (public domain), downloaded from https://huggingface.co/datasets/ncbi/TrialGPT-Criterion-Annotations. The source parquet SHA-256 is 14c547184fac9b013cd17441fd028845b40150c76b022e58334f5494077e5234. Trials here span medical specialties.

We ranked patient IDs by a fixed hash. The first ten and next ten form disjoint panels. Only rows marked training=false in the release were used. No other rows for those patients were used for authoring. The originating dataset does contain training rows for the same patients. These are held out within this experiment. General model pretraining exposure is unknown. ClinicalTrials.gov documents were not supplied to the benchmark author. Rules used the given criterion excerpts. In-session semantic authoring and chart abstraction were blinded to row labels and supporting sentence IDs. Executable rule drafts were captured before reviewing the narratives. Typed FHIR Observations represent the captured abstractions and link to exact numbered narrative sentences. Patient/encounter metadata is synthetic benchmark scaffolding. The replay automates evaluation; it does not demonstrate automatic extraction from unseen notes or independently validated clinical interpretations.

| Measure | First panel | Patient-disjoint retest |
|---|---:|---:|
| Patients / criteria | 10 / 36 | 10 / 35 |
| Physician definite decisions | 30 | 24 |
| PocketMD definite decisions | 4 | 1 |
| Definite decisions agreeing with physician | 4 | 1 |
| Exact sentence sets on definite decisions | 2 | 0 |
| Unresolved criteria with partial citations after feedback | 1 | 4 |

The improvement was routing and traceability. Decision coverage was unchanged on the retest. All five definite answers had at least one physician-cited sentence in common. For a strict exact status comparison, NIH has no protocol-review or human-action label. In round one exact state agreement changed from 10/36 to 8/36 as role-specific outputs replaced generic missingness. In round two it stayed at 11/35. Exclusion-positive means patient NOT_MET. An authoring hold is never counted as a correct missing-data label. A definite result on four pilot examples and one retest example cannot establish clinical accuracy. The eight original protocols were regression-tested separately from these mixed-specialty public cases.

For a developer repeat using the original public parquet, install DuckDB, then run the selection scripts, author scripts, prediction scripts, scoring scripts, and final summary. Keep the two panels separate. Prediction hashes are recorded before physician labels were read. The second-round revision hashes are under round2/REVISED.sha256. The original results.csv files are immutable comparison data. The all_results.csv file pairs both program dispositions with expert labels and citations.

# ClinicalTrialMaching
