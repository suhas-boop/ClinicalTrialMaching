# PocketMD engineering workflow

The main Codex session owns planning and prioritization. Delegate implementation to `pocketmd_engineer` and independent verification to `pocketmd_verifier`. Keep engineering orchestration in the development workspace. The deployed workflow uses the existing rule author, reviewer, compiler, evidence bindings and deterministic matcher.

## How the product should behave

1. Author a typed rule from a criterion, its governing protocol version and clauses, approved study answers, and a versioned evidence catalog. Preserve inclusion/exclusion polarity, grouping, thresholds, time anchors, entity identity and evidence qualifications.
2. If plausible interpretations change a result, record one discriminating question with its source excerpt and version. An authorized coordinator or investigator can answer. Save the answer, its author, authority and scope, reauthor and revalidate. Keep a clarification open if the answer leaves competing interpretations. Record engineering completion separately when a mapping is still outstanding.
3. Have the rule and the patient intake use the same evidence definition. For each fact specify the concept and coding systems, FHIR resource and element, required status, episode and temporal links, units where relevant, and source reference. Preserve original codes and text when normalizing. Extend a shared mapping for a demonstrated reusable gap.
4. For screening, show the criterion-level disposition and patient evidence. A missing record, an investigator assessment and a patient survey require distinct actions. A trial protocol question belongs to rule authoring and can affect many patients. Preserve a distinct engineering state for an unbound rule.

## Development and verification

Start from the most recent verified checkout. Use a separate working copy for changes to an archived release. Reuse the existing queues and replay receipts. Choose one hypothesis from a real discrepancy or newly available input. Record the input fingerprint, expected failure mechanism and distinguishing test. Skip an unchanged completed experiment.

Keep labels and reference queries in the evaluation path. Create separate author inputs and an evaluator-only reference file. For an evaluation that requires strict blinding, use distinct work directories or access controls so the author cannot read the references. Freeze generated rules, patient outputs and versioned source pointers before scoring. Once a scored item has guided a change it is development/regression data. Reserve disjoint patients and trials for a later generalization claim.

Record one receipt per distinct experiment with the source snapshot, dataset split, relevant code/catalog versions, prediction hash, replay command, counts, changed cases, conflicting evidence and disposition. Report engineering fixture results, real-chart experiments, the 134-assignment TrialGPT replay and its 91-case physician-definitive subset under their own names and denominators. Report false definitive decisions as well as agreements and abstentions. Give both the governing criterion and the exact patient evidence for every newly decisive strict result.

Continue engineering work independently. Deduplicate actionable notifications through the repository's existing reporting policy. Notify Suhas only for a verified increase under the agreed strict metric, the target, or a specific source or decision he can supply. Include the affected case, what was checked, and the exact source or answer needed. Preserve separate statuses for synthetic evidence, user-relayed answers, and verified study authority. External contact requires explicit authorization.

For current strict-evidence authority requests, run `python3 experiments/strict_evidence/active_authority.py` from this directory. The [workflow dispositions](experiments/strict_evidence/authority_dispositions.json) record dormant cases and the evidence that would reopen them.
