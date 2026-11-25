# PocketMD pipeline source

Start here after extracting the archive and opening the PocketMD folder. The core CLI is pocketmd.py. This package brings together the R21 research implementation and its subsequent combined TrialGPT replay. Older READMEs and stored outputs are preserved for reproducibility.

## Run one criterion from text through evaluation

Use Python 3.11 or 3.12. Commands below use python3. Choose fresh output paths. The recorded authoring demo needs no API key.

```sh
python3 pocketmd.py demo --out demo-output
```

The demo handles a clear criterion, a reviewer follow-up and an unresolved evidence binding. For the same synthetic ECOG 2 observation, the rule returns NOT_MET if only 0 and 1 qualify, and MET when the supplied reviewer answer also permits 2. Reviewer answers and model responses in this demo are fixtures.

To author new text, see criterion_workbench/README.md. Set OPENAI_MODEL and OPENAI_API_KEY in the environment for live model calls, or configure POCKETMD_MODEL_COMMAND. Supply only data authorized for that provider. The workbench has a bounded text-authoring catalog. The larger study packs and the TrialGPT benchmark use separately versioned rules and evidence mappings.

## Convert a patient note to FHIR and screen it

```sh
python3 pocketmd.py fhir-convert demo-bundle.json --note nih_benchmark/round12/example_note.txt --patient demo
python3 pocketmd.py fhir-screen --bundle demo-bundle.json --subject Patient/demo --study NCT02219360 --criterion 435
```

This example returns NOT_MET because a documented CT finding triggers the exclusion. Inspect criteria.435.evidence for the Observation reference. The note reader covers a bounded vocabulary and records source spans. An unmapped or absent finding can leave a criterion unresolved.

## Code map

| Stage | Source |
|---|---|
| Author, review, record answers, export rule | criterion_workbench/rules.py, text_author.py, openai_author.py |
| Validate typed expressions and evidence bindings | criterion_workbench/compiler.py |
| Benchmark evidence catalog and compiler | nih_benchmark/round9/clinical_fields.py and nih_benchmark/round11/catalog.py |
| Convert notes into FHIR evidence | nih_benchmark/round12/intake.py |
| Match source-backed patient facts to a criterion | nih_benchmark/round12/screen.py |
| Eight uploaded oncology protocols and their review questions | eight_rules/release/README.md, rules/, bindings.py, screen_study.py and review-questions.csv |
| Combined benchmark evaluation | nih_benchmark/reconcile/combined_replay.py |

## Reproduce the benchmark

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install duckdb==1.5.0
python3 nih_benchmark/reconcile/combined_replay.py combined-output
```

The runner verifies the original public patient notes and criterion text, then writes predictions before reading the reference labels. All 134 assignments are processed. Among 91 physician-definitive assignments, six agreed under strict scoring and nine agreed under the combined experimental policies. Both modes had zero definitive disagreements. The checked-in comparison outputs are in nih_benchmark/reconcile/. The full workbench test command is python3 pocketmd.py test. For PDF ingestion dependencies see criterion_workbench/requirements.txt.
