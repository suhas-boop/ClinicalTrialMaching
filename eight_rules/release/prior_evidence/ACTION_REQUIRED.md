# Decisions and source requests

## Request the current Philogen protocol

**To the site coordinator for PH-L19TNFDOX2, Site 65**

The site packet includes the complete 3 July 2024 protocol v6.0. The supplied approval refers to v7 dated 17 December 2024. Could you provide the full protocol and amendment currently in effect at Site 65, together with its effective date? If a later amendment supersedes v7, please send that version. This determines which eligibility criteria and assessment schedule PocketMD should use.

All 43 Philogen entries and all five of its tested criterion evaluators carry the historical v6 scope. Reconcile every affected rule against the replacement before current-site use.

## Raise a question when the answer affects a rule

| Study and item | Decision-changing example | Who can establish the answer |
|---|---|---|
| SOTIO 106S01 I18 | Prior treatment ended eight months before screening. Progression was documented two months before screening. Does the six-month requirement govern progression alone or also the treatment event? Which treatment milestone is used? | Trial coordinator can locate the governing instruction or route the question to the sponsor or investigator. |
| Michigan NCT05653388 | The patient has already received a first dose. Baseline specimens and scans were obtained before that dose. May eligibility assessment or study entry take place now? | Study authority for the enrollment interpretation. Record the dated answer and its scope. |
| NEOK001-1 E15 | Three baseline QTcF readings straddle the threshold. Which reading or aggregation governs the decision? | Use a governing ECG procedure if supplied, otherwise request a protocol-authorized interpretation. |
| Boehringer 1479-0032 I09 / E04 | A patient meets the stated autoimmune exception under I09. Does it also apply under E04? | Sponsor or designated protocol authority if the two provisions lead to different decisions. |
| DualityBio DB-1311-O-1001 I07 | The printed INR/PT wording and two discordant measurements lead to different results. Which test or combination governs? | Governing laboratory instruction or authorized trial interpretation. |
| Parabilis FOG-001-301 | A branch depends on a central read, prohibited medicine or a signed form whose trial-specific instructions are absent from the upload. | Site or sponsor supplies the actual governing artifact or decision for that branch. |
| Recursion REC-1245-101 | An otherwise qualifying adolescent is screened. Is their site authorized for this population and is the selected cohort open on that date? | Dated site/sponsor activation record. A patient attestation cannot prove that state. |

This is a short decision queue. Each study JSON carries additional branch-specific conditions under `issues` and `criteria[].remaining`. No external messages were sent.

## Who owns the rest

**Codex** owns parsing, query construction, catalog binding, timing, normalizing units, testing forbidden substitutions and replaying regressions. Hospital integration needs the actual site dictionaries, FHIR capabilities and de-identified examples before promoting a local mapping. A missing field in one example is insufficient grounds to expand the patient model.

**The coordinator** supplies dated operational records such as cohort activation, applicable manuals, screening and study events. A trial-onboarding test clock is suitable only for tagged simulation.

**The investigator or participant** supplies an actual patient-specific answer when the criterion requires judgment or self-report. The system records the question, respondent, study, timing and linked evidence. A missing measurement routes to records retrieval. A protocol ambiguity stays with rule authoring until a governing answer is available.
