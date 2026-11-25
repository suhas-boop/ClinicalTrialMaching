# PocketMD TrialGPT abstention audit

Replay all 134 frozen assignments from the original notes, then compare predictions to the published labels. The package includes prior release material. Files under round12/results and round12/export remain historical R12 receipts. The R13 raw replay builds new bundles in memory. The eight-study suite has a separate population.

## Audit deliverables

- 85_case_audit.csv contains the rule, its primary blocker, the available and required facts, applicable FHIR selectors, reviewer-cited sentences when supplied, an engineering review of the evidence gap, and the specific request. The source document ID and cohort are retained. Each row counts one patient–criterion pair.
- action_queue.csv deduplicates requests using the engine's existing IDs. Across this slice there are 93 record requests, 15 protocol questions, 6 investigator requests, 2 patient requests, and 1 subject-identification request. A single patient rule can have several requests. Not every record lookup needs a clinician.
- 134_predictions.csv, summary.json and raw_traces.json record the full replay. Rules and the catalog are frozen. Benchmarked decisions remain 6 of 91 physician-definite pairs; all six agree. Of the 85 abstentions, 48 physician labels have no supplied sentence citation, including 34 of the 59 missing-data pairs. An empty citation list does not prove a reference label is wrong. The remaining 37 have cited sentences; the audit retains them for comparison with the precise rule requirements.
- R13 adds source-linked qualitative exam findings for two audited traces, 186 and 187. These findings cannot fill a numeric rate. A synthetic follow-up note with a measured rate can. A quantitative FHIR Observation can use its standard coding without a redundant local code for the supported quantitative selectors. Patient identity, provenance, source profile, scope and UCUM checks still apply. Multiple incompatible codes stay unresolved.
- Two rule-authoring review candidates merit attention beyond the existing protocol queue. In 322 the original text qualifies both branches by population, while the frozen tree tests pregnancy directly in one branch. In 965 the note documents thrombocytopenia on the current CBC, but the rule asks for known history. Ask the protocol authority whether a newly documented qualifying finding satisfies that wording. These audit findings are flagged in the case rows; the frozen rules and existing queue counts do not incorporate new interpretations.

## Reproduce

From the extracted release root with Python 3.11 or later:

    python pocketmd.py audit-abstentions
    python nih_benchmark/round13/test_changes.py
    python nih_benchmark/round12/test_pipeline.py
    python nih_benchmark/round11/test_catalog.py
    python nih_benchmark/round11/check_mappings.py
    python pocketmd.py test

For a single note, use pocketmd.py fhir-convert followed by pocketmd.py fhir-screen as described in the historical README below the R13 introduction. An individual input note or a newly converted export is required to see a new extracted finding. A record retrieval request identifies evidence to seek. This replay has no external hospital chart connection. The case audit is retrospective engineering review, not independent clinical adjudication.
