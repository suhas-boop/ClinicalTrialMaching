# PocketMD · Michigan and SOTIO screening

This research release runs all three eligibility criteria from the University of Michigan leiomyosarcoma biomarker study (NCT05653388, March 2025 update) and all 42 from SOTIO Biotech 106S01 (version 2, amendment 1, 14 August 2026). It evaluates one indexed patient and study at a time. All examples and acceptance tests are synthetic.

## Run locally

Use Python 3.11 or newer with the cryptography package installed. Extract the ZIP, open its directory, and run:

```bash
python -m pip install cryptography
python -B screen_study.py --list
python -B screen_study.py --demo michigan-order-only
python -B screen_study.py --demo sotio-fresh-biopsy
python -B screen_study.py --demo sotio-liver-panel
python -B screen_study.py --packet examples/sotio-drug-washout.json
python -B verify_release.py
```

## What's executable

Each run returns a decision or an explicit reason to pause for every criterion, with evidence references where available. A MET for one row applies to that row only. Each exclusion is evaluated as a requirement to pass screening, so documented exclusion gives NOT_MET. No whole-study enrollment authorization is generated.

- Michigan's three rules check LMS and extent on the same cancer episode, first-line therapy, and measurable disease. All 38 frozen patient scenarios are in `examples/`. The therapy rule can ask for a protocol interpretation on an order alone or a liposomal product. An unresolved local histology or drug code can separately require an engineering mapping. The timing of formal enrollment relative to first dose remains a separate study question.
- SOTIO has 22 inclusion and 20 exclusion rules. Six contain branches where competing interpretations can change the outcome. See `study-index.json` for the exact question and protocol locator for I06 (archival biopsy when fresh is feasible), I11 (discordant coagulation results), I18 (progression relative to prior treatment), E08 (treated CNS disease with persistent symptoms), E11 (virus-specific exceptions), and E14 (older ongoing cardiac conditions). Cohort openings, regional approvals, signed clinical assessments, patient preferences, and missing records can independently require action on other criteria.
- Fifteen SOTIO criteria reuse the existing research evaluator with two scoped corrections. Twenty-seven execute on source-linked typed facts using `sotio_rules.json`. Seven of those 27 have additional tested adapters for selected facts on more direct FHIR records: I01, I10, I11, I14, I17, E05 and E17. For example, a raw weight measurement can contribute to I01, while adolescent authorization still comes from the site. Two code systems or units with different meanings must be reconciled before entering the profile. The drug adapter requires verified exposure and appropriate half-life evidence when applicable.

## Evidence and human actions

The input envelope is `{context,bundle}`. The bundle is a FHIR collection with versioned resources. Michigan uses a patient, indexed condition and calendar-day cutoff. SOTIO uses the study, amendment fingerprint, patient, screening encounter, disease episode, site time zone and cutoff instant. Examples specify the research mappings and trusted identities used in that scenario. These demonstrations accept configured trust metadata from the local caller. A production intake service must verify identity, authority, mappings, provenance and cutoff independently before emitting a packet.

The local normalized FHIR profile connects each qualifying fact to a same-patient source and an explicit role. Source text, locator, logic and evidence expectations are in `sources/`. Candidate standard codes and their sources are in `terminology.json` and `TERM_REVIEW.md`. A candidate code needs a site-specific crosswalk and a verified extraction path before live use. The new rules' fact contracts are in `sotio_rules.json`; a clinician's judgment should be collected in the scoped assessment defined there. Presence of an isolated diagnosis or medication name does not establish all the required qualifiers.

MET and NOT_MET indicate an evaluated result. MISSING_DATA, INVESTIGATOR_ACTIONS, and PATIENT_SURVEY route patient follow-up. STUDY_ACTION requests a dated study or site decision. AUTHORING_HOLD requests protocol clarification and BINDING_HOLD requests a mapping. Simulated schedules are identified in the pinned screening examples. Replace simulations with verified cycle dates for operational use.

Fresh-biopsy and archival-biopsy are alternative histories for one synthetic patient. Missing-records and six additional source-specific examples demonstrate missing facts, consent, hepatic and coagulation tests, ejection fraction, heart rate, and medication washout. A patient record can legitimately produce several different action types. Retain the reason and trace per criterion.

## Verification

`verify_release.py` replays all 274 specifically authored SOTIO cases, safety/identity controls, direct FHIR adapter controls and the original pinned regressions. It executes each of the 47 bundled whole-study packets and compares Michigan to the frozen outputs. These provide engineering evidence on simulated inputs. Independent clinical adjudication and validation on a representative hospital feed remain open.
