# Michigan and SOTIO research runtimes

The bridge evaluates three Michigan criteria and fifteen SOTIO criteria on versioned FHIR R4 collection snapshots. Both SOTIO examples represent alternate screening histories for one synthetic person and screening encounter. Every example is synthetic. Site terminology mapping, trusted-form integration and clinical validation remain separate from these replay results.

Use Python 3.9 or later with the existing research environment's `cryptography` dependency for Ed25519 verification. From the directory containing this file, run:

```sh
python -B bridge.py michigan michigan_demo.json
python -B bridge.py michigan-demo order-only
python -B bridge.py sotio sotio_demo.json
python -B bridge.py sotio sotio_archive.json
python -B bridge.py regenerate
python -B bridge.py verify
python -B export_michigan.py
```

The Python entry points are `run_michigan(bundle, patient, episode, as_of)` and `run_sotio(bundle, patient, encounter, as_of, *, timezone_name, onboarding, trusted_signers)`. Michigan takes a YYYY-MM-DD calendar day and a single indexed disease episode. SOTIO requires a timezone-qualified timestamp and a screening Encounter. Use a separate, trusted signer registry for real SOTIO form verification. The included registry and private keys are deterministic research fixtures.

Each result contains its state, reason and versioned resources. Michigan outputs retain the query requests, per-fact trace, Boolean tree and source paragraph. `rule_metadata.json` lists the source wording, locator, published evidence expectation and exercised holds. Complete Michigan eligibility has three numbered bullets. Consent, assent if applicable, and study entry processes appear separately in the pinned Michigan source packet. Historical trial-wide questions still require their recorded authorities.

`legacy_replays.json` contains 38 Michigan scenarios (114 outcomes) and two SOTIO scenarios (30 outcomes). The SOTIO fresh-biopsy and archival-only examples differ in tissue/assay evidence and biopsy feasibility. The latter demonstrates the conditional I06 protocol question. For the demonstration only, the onboarding profile sets C1D1 seven days after trial onboarding. Source-linked simulated transfusion in both scenarios makes E04 fail. The output includes the simulated schedule for affected criteria.

For clinical schedule integration, the normalized screening Encounter may carry a final, versioned Observation using the local research system `urn:pocketmd:research:sotio-milestone` and code `C1D1-actual` or `C1D1-planned`. Its `valueDateTime` contains the calendar day. It belongs to the screened patient and Encounter and has a versioned `derivedFrom` link to a current same-patient DocumentReference that was available at cutoff. A documented actual date takes priority over a plan. Conflicting dates of the same priority require reconciliation. Plans remain labeled explicitly in the result through `schedule_basis`.

Two signed-protocol corrections run in `amendments.py`. Exclusion 4 uses a strict threshold of less than fourteen calendar days before C1D1. At the 14-day boundary, a pass requires documented history covering the full window. Inclusion 12 verifies a linked serum specimen because LOINC 1751-7 also permits plasma. These corrections leave the original programs and historical controls in `pinned/` intact.

`verification.json` records 227 original cross-study controls (overlap with Michigan possible), 11 original SOTIO E13 authentication controls, 114 Michigan expected results, 30 SOTIO scenario results, and focused amendment and input controls. A protocol-authoring or terminology hold remains a distinct engineering disposition. A missing patient observation, required investigator assessment, or outstanding patient survey can be a valid runtime output.
