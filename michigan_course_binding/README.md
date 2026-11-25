# Michigan first-line chemotherapy binding experiment

A structured synthetic oncology chart was written to a disposable HAPI FHIR 5.4.0 server running FHIR R4 4.0.1. The test evaluated the chemotherapy criterion in the uploaded March 2025 Michigan LMS protocol (NCT05653388, §2.1, bullet 2). The rule was authored manually for this experiment. It returns a criterion-level screening decision or records why a decision is withheld.

## Main finding

The patient, disease episode, administered product, administration resource version and other current drug were held fixed. Only MedicationRequest.basedOn was edited to identify the current course, then the prior course, then the current course again. The current first-line regimen had a dated receiving-status assertion and an explicitly complete inventory. With conventional doxorubicin and ifosfamide in that course the outcome was MET. Moving the doxorubicin order to the prior localized episode left only ifosfamide in the current regimen and produced NOT_MET. Restoration produced MET. Removing the course link altogether in a separate case produced MISSING_DATA.

All 19 prespecified outcomes across 17 baseline charts and two mutations matched. Four were MET, three NOT_MET, eight MISSING_DATA and four were withheld upstream. The holds concern protocol interpretation or an unverified terminology mapping. They do not add any categories to the five patient-screening outputs.

## Inputs and binding

- cases.json declares synthetic chart facts and the expected outcomes. The ingester writes only the clinical fixture fields. The evaluator never receives the expected outcomes.
- fixtures.py writes Patient, Condition, CarePlan, Observation, MedicationRequest and MedicationAdministration resources. Treatment line, completeness of the regimen inventory, and current treatment confirmation are structured fixture assertions with explicit local codes and dates. They are supplied chart evidence. Stage and episode selection are inputs to this test.
- evaluate.py reads the selected disease record and searches by patient for plans, observations, orders and administrations, following pagination. It checks course period, patient, episode, line and current treatment evidence. A completed administration must be linked through its order to the course. Only realized, qualifying evidence counts. Negative inference requires an explicit inventory-completeness assertion.
- catalog.json pins the small terminology subset used here and its public sources. Conventional product 1191138 is linked to active moiety 3639. The Doxil formulation retains its separate identity. Its eligibility under this protocol remains an authoring question. A known AIM regimen name yields candidate components from SEER*Rx and requests actual product/formulation evidence for this implementation. An unknown site name stays with the terminology owner. In a real source, the site would also need to verify the approved local regimen-name mapping.
- results.json contains actual outcomes, issued searches, resource and order versions, medication product codes, course links, and reasons. A fixed synthetic decision date is used. All records are synthetic.
- check_traces.py verifies the outputs and the identifying invariants of the paired comparison.

## Replay

Use Python 3.12+ and Java 11. From the extracted directory run:

```sh
python3 replay.py --java-home /path/to/java11 --out replay-results.json
python3 check_traces.py replay-results.json
```

The bootstrap reuses the earlier PocketMD test server setup. It starts an isolated loopback HAPI server and shuts it down after the run. Cached assets can be supplied with --cache; a clean setup downloads the checksum-pinned server assets. To use an already-disposable localhost R4 server supporting client-assigned IDs and transactions, run python3 run.py http://127.0.0.1:8080/fhir --out replay-results.json instead.

## What the run establishes

The tested FHIR resource structure and a small source-linked terminology catalog can express this binding without a per-patient doxorubicin-based flag. This run starts with structured, explicitly linked evidence and uses a hand-built deterministic rule and binder. It does not establish free-text extraction, autonomous LLM rule generation, production chart completeness, all FHIR representations, clinical approval or accuracy on real patients. The tested scope covers one active course, fixed-date snapshots, the enumerated products and direct relative references. A named historical regimen or an earlier completed dose alone is insufficient evidence of current treatment. For transfer testing, establish course identity, line, current state and component relationships from an independently annotated source record before evaluating the same rule.
