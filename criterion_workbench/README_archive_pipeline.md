# PocketMD criterion pipeline

PocketMD takes one eligibility criterion, the governing protocol and a shared clinical evidence catalog. An LLM drafts a structured rule or asks the trial team a question. A compiler verifies the source, evidence selectors and execution plan. A deterministic engine applies a released research rule to a patient’s FHIR R4 collection Bundle. Only the screening stage receives patient records.

## Run the offline demo

Use Python 3.10 or later. Extract the ZIP, open a terminal in the extracted directory, and run:

```sh
python3 -m pip install -r requirements.txt
python3 demo.py
```

The demo uses temporary local state and makes no model calls. It includes one criterion and the matching protocol from each of the four uploaded trials. All patient records and all answers used in automated tests are synthetic.

| Example | What to expect |
|---|---|
| NEOK001-1, inclusion 2 | An in-session model authored the inclusive age rule from the source packet. The demo replays that saved response. The engine returns MET on the 18th birthday, NOT_MET one day before, and MISSING_DATA without a birth date. The trace identifies the patient and screening encounter versions. |
| SOTIO 106S01, inclusion 18 | The first response from the earlier blinded authoring experiment opens three protocol questions and four evidence-mapping gaps. Replaying the same response adds zero new items. The six-month interpretation remains open. |
| REC-1245-101, inclusion 5 | A reference-derived rule evaluates the adolescent Lansky branch. The test exercises scores of 70 and 60. |
| Michigan LMS, inclusion 1 | A reference-derived rule retrieves the diagnosis and metastatic or unresectable status for the index cancer. Moving the metastasis evidence to another episode changes the test result to MISSING_DATA. |
| New synthetic PDF study, minimum age 21 | The upload was outside the four-site inventory. The rule stays on hold until a separate, fixture-specific research reference is supplied. Its controls cover above, below, exact birthday and missing birth date. The accepted plan runs on the synthetic patient. |

## Run one criterion

```sh
python3 pipeline.py run NEOK001-1-I02 \
  --site examples/NEOK001-1-protocol.zip --response examples/age-author.json \
  --bundle examples/patient-age.json --patient synthetic-age-example \
  --encounter synthetic-screen --as-of 2026-11-20T10:00:00Z
```

The JSON response includes the executable, its catalog selectors, the patient result, the evidence references and a run ID. Here the executable reads age in completed calendar years from the verified patient birth date at the screening run date. Omit the patient arguments to compile a rule on its own. To screen a later version of a patient’s record, use the run ID with the new Bundle and cutoff. The engine reevaluates that criterion and checks whether its reviewer context has changed.

```sh
python3 pipeline.py screen RUN_ID --bundle examples/patient-age.json \
  --patient synthetic-age-example --encounter synthetic-screen --as-of 2026-11-20T10:00:00Z
```

Specify an offset timestamp for reproducible replay. Omitting it uses the run clock. An optional site timezone and a native onboarding profile are accepted. The existing simulated cycle-start convention is available through a research onboarding profile. The generated age example and SOTIO progression example do not require a cycle-start assumption.

## Author a fresh rule

Use the locally configured Codex CLI or a trusted program that accepts packet JSON on stdin and returns one draft object on stdout. The command runs once per request. A fresh private author receives the source document, relevant page images or Word paragraph locator, governing context, the shared catalog and any applicable reviewer answers. Use a provider authorized to process the study protocol. No patient Bundle is included.

```sh
python3 pipeline.py run NEOK001-1-I02 --site examples/NEOK001-1-protocol.zip --codex
python3 pipeline.py run 106S01-I18 --site examples/106S01-protocol.zip --codex --web response
```

With the Codex adapter, each optional public lookup gets a predefined terminology topic. Available topics are response, drug, histology, performance and labs. The public worker receives only generic search terms. Retrieved codes are candidates. A verified local catalog mapping still determines which patient field, coding, unit, episode and timestamp can satisfy the rule.

The included Responses API adapter supports a configured OpenAI API key and an explicitly selected model. Supply the key in the process environment. Keep credentials out of the command string and the packet.

```sh
python3 pipeline.py run NEOK001-1-I02 --site examples/NEOK001-1-protocol.zip \
  --author-command 'python3 openai_author.py --model YOUR_MODEL'
```

For another model backend, set `POCKETMD_AUTHOR_COMMAND` or pass `--author-command`. For an external review of the model input, `pipeline.py packet` takes the same source flags and an `--out` path and prints the input hash. A raw historical draft can be imported before any answer has been recorded. After feedback, import a JSON envelope containing `author_input_sha256` and `response` from the updated author pass. An executable draft must identify all the reviewer answers it applied.

The positive NEOK response came from a fresh in-session author that received the source packet and the supported comparator syntax. No patient labels or reference rule were supplied. A separate attempt to start the standalone Codex CLI on a fictional protocol stopped during startup because its application state was read-only in the build environment. The Responses API transport was tested with simulated provider responses. A live deployment needs its own configured provider.

## Onboard a criterion from a new PDF

Start with `examples/intake-age/manifest.json`. Supply the study and criterion IDs, inclusion or exclusion polarity, original text, section, 1-based PDF page, protocol version and SHA-256 of the original PDF. Omit the synthetic-fixture flag on real studies. The loader checks that the text occurs exactly once at the specified location after whitespace normalization, verifies the PDF digest and attaches the original source. A scan with no matching text layer needs a separately verified transcription. This release takes one submitted criterion at a time.

```sh
python3 pipeline.py run POCKETMD-SYNTHETIC-AGE-I01 \
  --manifest examples/intake-age/manifest.json --protocol examples/intake-age/protocol.pdf \
  --response examples/intake-age/author.json --review examples/intake-age/review.json \
  --bundle examples/intake-age/patient.json --patient fixture --encounter screen \
  --as-of 2026-11-20T12:00:00Z
```

For an existing four-site criterion, the compiler compares the generated expression and bindings against the sealed reference. For newly submitted or previously unimplemented criteria, the first new execution template supports an inclusive minimum age at screening. An independent reference must identify the precise source, interpretation, rule and reviewer-answer hashes, evidence binding and expected control results. For real uploads the review must be attributed to a human. The included fictional reference is accepted only for the exact fictional source. This local prototype trusts reviewer attribution entered by the operator. Other new operators or unverified hospital contracts remain visible as review or validation holds.

## Questions and actionable events

```sh
python3 pipeline.py run 106S01-I18 --site examples/106S01-protocol.zip \
  --response examples/i18-author.json --events-only
python3 pipeline.py actions
python3 pipeline.py questions
```

`--events-only` emits newly opened questions and engineering gaps, plus failures that require attention. It stays quiet on an unchanged replay. `actions` shows the outstanding work by owner. Questions use the study, criterion and protocol hash. Existing questions and verified aliases retain their identity. Unverified paraphrases can remain separate for review. Versioned evidence gaps are kept in a separate engineering ledger. No messages are sent to clinicians by this CLI.

Record an actual coordinator or investigator response with its source and decision date. Then resume the saved run using the same protocol. The new run links back to its parent and includes the scoped answer. A changed answer set prevents the old run from producing a patient result.

```sh
python3 pipeline.py answer QUESTION_ID --answer "Documented answer" \
  --authority "Name or authorized role" --date YYYY-MM-DD --source "Decision record and location"
python3 pipeline.py resume RUN_ID --codex --events-only
```

The five per-criterion patient outputs are MET, NOT_MET, MISSING_DATA, INVESTIGATOR_ACTIONS and PATIENT_SURVEY. An unresolved trial interpretation or unverified evidence binding stays at authoring. A patient-specific judgment or patient response is routed when the released rule requires it.

## Evidence and verification

The shared selectors live in `runtime/catalog.json`. The research normalizer retains local coding and adds the verified demo translation where the demo mapping exists. For example, it maps the synthetic hospital ECOG code to the catalog’s standard code. Actual hospital mappings, authentication, ongoing notification delivery, and independent clinical validation remain deployment work. The five outcomes refer to an individual criterion. Trial-wide enrollment and real-patient eligibility were outside this evaluation.

The Michigan study also uses its sealed episode-based evidence catalog. Its screening command requires `--episode` with the logical ID of the patient's index cancer Condition. Its results retain the disease-episode evidence returned by the Michigan evaluator. Other indexed studies use the study screening encounter.

Two additional compatibility tests use reference-derived drafts. REC-1245-101 I05 checks the adolescent performance-status branch. Michigan MI-LMS-01 checks the disease episode and returns the underlying FHIR requests and fact-level evidence. To run the Michigan example:

```sh
python3 pipeline.py run MI-LMS-01 --site examples/compat/NCT05653388-protocol.zip \
  --response examples/compat/mi-reference-draft.json --bundle examples/compat/mi-patient.json \
  --patient demo-compat-met-p --episode demo-compat-met-current --as-of 2026-04-15T12:00:00Z
```

Run history defaults to `pocketmd-state/`. To select a different directory, place `--state-dir PATH` before the subcommand. Each authoring directory stores its versioned packet, first provider response or failure, compiled rule and receipt. Access to the state directory also grants access to its protocols and any saved screening evidence references. The demo performs all writes in a temporary directory.

```sh
python3 -B -m unittest discover -p 'test_*.py' -v
python3 -B runtime/verify.py
```

The four-site baseline was retained in `runtime/`. Its original test suite covers the existing patient engine. The top-level tests cover author transport, separate terminology lookup, packet integrity, compilation, review and independent reference intake, deterministic screening, stale answers, and idempotent actions. See `verification.json` for the packaged run results and provider-test scope.
