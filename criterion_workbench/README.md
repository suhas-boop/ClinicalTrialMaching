# PocketMD criterion authoring

Turn a single trial criterion, its protocol context and a selected evidence catalog into a reusable research rule. A model proposes the interpretation. A second model call reviews the obligations against the source. The compiler checks the expression and its bindings. Patient screening uses the accepted expression deterministically.

## Run the worked example

On macOS or Linux, use Python 3.10 or newer. From this folder, run:

```bash
python3 demo_rule_loop.py --out demo-output
```

This replays recorded in-session author and verifier judgments, processes the investigator replies, saves the exported rules and screens a synthetic patient. It uses no service credentials. The demo includes two independent hypothetical answers for the same study wording. Each has its own case history. A screening ECOG of 2 returns `NOT_MET` when the answer permits scores 0 or 1 and `MET` when the answer permits 0, 1 or 2. “Use the usual scores” produces a follow-up question. A clear serum albumin clause with no selected mapping goes to engineering.

See only items needing a decision, without sharing screenshots. The investigator queue lists open study questions. The engineering queue lists mapping or validation work. Answered questions disappear from the current queue.

```bash
python3 rules.py actions --work demo-output/work --owner investigator
python3 rules.py actions --work demo-output/work --owner engineering
```

To run one exported rule immediately:

```bash
python3 rules.py screen \
  --rule examples/text_workflow/example.rule.json \
  --bundle examples/text_workflow/patient-score-2.json \
  --patient demo --encounter screen --as-of 2026-05-01T19:00:00Z
```

The result includes versioned evidence references. The example rule records the criterion, the question, the attributed synthetic answer, its catalog selection and both model judgments. Inspect the JSON to see precisely what can execute.

## Author a new criterion

Choose a model with JSON output available in your account and set `OPENAI_MODEL` and `OPENAI_API_KEY` in your environment, or set `POCKETMD_MODEL_COMMAND` to an approved local adapter. Model calls receive the criterion, supplied context, answers and catalog. Patient screening runs locally. Use receipts and credentials appropriate to your study.

```bash
python3 rules.py build --work ./rules-work --study EXAMPLE --version amendment-1 --id I06 \
  --criterion "Participants must meet the study’s ECOG requirement at screening." \
  --context "ECOG is assessed at the screening encounter." --polarity inclusion --facts ecog
```

You can supply `--context-file protocol-excerpt.txt` with the governing excerpt and page or section locators. Include the inclusion or exclusion heading when a fragment such as “ECOG 3 or higher” depends on it. The rule evaluates to true when the inclusion is satisfied or the patient is clear of the exclusion.

| Authoring result | Available action |
|---|---|
| `EXECUTABLE` | Export the reusable JSON rule and run it on standardized FHIR bundles. |
| `INVESTIGATOR_REVIEW` | Answer the numbered question for this criterion and protocol version. |
| `BINDING_REVIEW` | Engineering supplies a verified mapping, evidence relationship or operator for the missing obligation. |
| `VALIDATION_REVIEW` | Inspect the recorded authoring discrepancy. Retry after addressing the defect. |
| `AUTHORING_ERROR` | Check model configuration or adapter availability and retry the saved inputs. |

If question Q1 asks which screening ECOG scores qualify, record the answer actually received. The following is a fictional worked answer:

```bash
python3 rules.py answer --work ./rules-work --study EXAMPLE --version amendment-1 --id I06 \
  --question Q1 --reviewer "Demo investigator" --answer "At screening, ECOG scores 0, 1, or 2 qualify."
python3 rules.py export --work ./rules-work --study EXAMPLE --version amendment-1 --id I06 \
  --out ./I06.rule.json
```

`answer` saves the reply and automatically runs the author and verifier against the original text, the question and the answer. Vague replies can generate another question. A provider failure leaves the reply available for `retry`. An identical completed request reuses its saved result. Each distinct study, amendment and criterion has its own revision history. `show` gives the current state, and `history` lists recorded events. The reviewer's name is recorded as supplied. Clinical identity verification and production release approval are integration work.

## What the selected catalog supplies

This text-authoring release includes two tested bindings from the four-study research catalog. Select either or both with `--facts`.

| Clinical fact | Normalized patient evidence | Execution scope |
|---|---|---|
| Age in completed years | `Patient.birthDate` and the study screening `Encounter.period.start` | Local calendar date at the start of the selected encounter. The as-of cutoff controls which record versions were available. |
| Screening ECOG score | `Observation.code` with LOINC `89247-1`, normalized `valueInteger` and a versioned source document | The same patient and study screening encounter, with effective time and final result available at cutoff. Conflicting scores require resolution. |

The language supports numeric comparisons, exact set membership and combinations with `all` and `any`. A clear clause outside these bindings goes into engineering review. An investigator’s interpretation supplies trial meaning. A required patient-specific assessment or survey still needs an evidence mapping and a response for the individual. The data intake boundary is a normalized FHIR collection Bundle. Hospital code crosswalks, live OncoEMR queries and deployment validation are outside this release.

## What the trial example revealed

The included real-source example uses NEOK001-1 Amendment 2, inclusion item 2 on page 49 and the screening failure provision on page 54. The rule needs to know whether the patient was already 18 at the beginning of the screening period. A patient could turn 18 between two visits. The supplied mapping establishes age at the selected encounter. That encounter’s identifier alone cannot establish that it began the entire screening period. Both model passes routed this version to binding review. This is an engineering interpretation of the supplied passages, pending independent clinical validation. The earlier age example used a narrower source packet. Its result and original instructions remain in `README_archive_pipeline.md`.

## Verification and provider modes

`examples/text_workflow/cases.json`, `author_responses.json` and `verifier_responses.json` contain the packets and separately generated model decisions. The supplied replay adapter recognizes these exact examples with their written catalog and candidate. Fresh text requires a configured model. In the hosted configuration author and verifier run in separate requests using the configured model. The export checksum supports integrity checks. Deployments can pin an expected checksum via `--expected-sha256` and compare the expected study, version and criterion on the screening command.

The supported normalization and provenance are research contracts. The synthetic reviewer identities, patient measurements, clinical interpretations and in-session model judgments carry no site or clinical approval.

To run the complete test suite, including the earlier PDF workflows:

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest discover -q
python3 runtime/verify.py
```
