# PocketMD · Rules for eight uploaded protocols

This is an offline research release for the supplied protocol versions. It contains 272 numbered criteria. Recursion also has 17 separately labeled appendix, schedule or reference entries. A criterion result applies to one patient, episode, study version and screening snapshot. It does not establish trial enrollment or clinical validation.

## Run the rules

Unzip into an empty folder. From that folder, run with Python 3.10+ using only the standard library.

```sh
python3 -B screen_study.py --list
python3 -B screen_study.py --rule NEOK001-1 NEOK001-1-I02
python3 -B screen_study.py --case NEOK001-1 NEOK001-1-I02 1
python3 -B screen_study.py --demo michigan-all-met
python3 -B screen_study.py --packet examples/1479-0032-met.json
python3 -B screen_study.py --rule REC-1245-101 AC01
python3 -B verify_rules.py
```

The packet command returns every numbered criterion for the selected study. Recursion adjunct results appear under a separate `supplemental` key. `--case` runs a specified synthetic case from one of the six typed packs. The two retained studies use their existing named demos. Case dispositions include MET, NOT_MET, MISSING_DATA, INVESTIGATOR_ACTIONS and PATIENT_SURVEY. The engine reports cohort/phase inapplicability, site operations, authoring uncertainty and unavailable evidence mappings distinctly. A patient with missing observations does not acquire an implied negative medical history.

## Locate a rule or source

| File | Contents |
|---|---|
| `rules-index.json` | All 272 numbered rules keyed by study and criterion, each with source wording, locator, checks, and either a typed expression or its executable entry point |
| `rules/<study>.json` | Six new machine-readable study packs, with predicates, accepted typed evidence, applicability, clarification branches and example inputs |
| `previous_focal/` | Pinned Michigan and SOTIO evaluators, mappings, original examples and verification |
| `sources.json`, `source_criteria/` | Uploaded protocol member names and fingerprints, governing context and criterion-level source excerpts |
| `typed-evidence-contracts.json` | Required local evidence for the six packs, including role, type, scope, and every consumer of the contract |
| `prior_evidence/` | Earlier eight-study terminology references, standard-code candidates, retrieval plans and specialized FHIR adapters. Its older coverage tally describes that earlier release |
| `review-questions.csv` | Study and criterion for each open interpretation or version dependency. Consult it only when the branch affects a case |
| `coverage.csv`, `verification.json` | Numbered coverage, criteria with scoped conditions and synthetic replay results |
| `SHA256SUMS` | Integrity checks for the distributed implementation, inputs and reference receipts |

## How evidence reaches a rule

The six typed packs expect final research-profile FHIR Observations with a pinned local evidence code. To implement a site adapter, find the underlying fact definition, resolve its clinical meaning against the hospital's source and standard vocabulary, and validate the clinical context (episode, clinical time anchor, unit, author, procedure or drug state as specified). Bind only the verified mapping. An external site assessment, investigator opinion or patient response must retain its actual origin. One normalized finding may require several raw records and calculations, such as a series of ECGs or a dated treatment history. Sample packets show the representation expected *after* this work. Contract hashes identify PocketMD definitions; they are not standard medical codes.

The binder checks study/version, patient, screening encounter, episode, observation status and cutoff, data type, numeric unit, source version and permitted author/performer. Numeric inputs with derived units use the PocketMD research unit namespace. Conditional expressions preserve exceptions and phase applicability. Supporting Observation and DocumentReference versions appear in each criterion response. Scope-qualified facts, derived calculations and reconciled negative findings must be established by a verified upstream producer. The synthetic context supplies a trust configuration. A hospital integration must issue this configuration server-side. There is no site-approved OncoEMR crosswalk in this release.

The previously tested raw-evidence adapters and their checks are preserved in `prior_evidence` and `previous_focal`. The six-pack input profile does not automatically transform arbitrary hospital FHIR resources. Source clinicians have not independently adjudicated the new rule packs or their case labels.

## Protocol scope

Philogen v6 is historical. The uploaded approval cites v7. All 43 current-screening results are held pending the complete site-effective protocol and its effective date. A historical replay requires the exact v6 fingerprint plus `context.purpose = "historical_replay"`. Boehringer Ingelheim 1479-0032 is the uploaded postoperative HER2-mutated NSCLC study. The eight uploaded files cover different indications, phases, cohorts and enrollment events.

The typed packs execute one numbered criterion at a time. Cross-references, site operations, baseline assessments and additional governing clauses are retained with citations. An unimplemented hospital mapping, unresolved branch, or missing clinical record can still require human action. Synthetic checks confirm program behavior against the authored expectations. The original uploaded documents are identified by hash and are not redistributed in full here.
