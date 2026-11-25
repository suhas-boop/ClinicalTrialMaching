# Same-episode stroke diagnosis and cranial imaging

**Disposition: retain the extraction finding and reject this decision rule for strict release.** The blind replay changed one result, case 817. Independent scoring after the freeze found that the physician reference was indeterminate on this case. Strict agreements remained 6/91, with zero opposite definitive decisions, 85 abstentions on the 91 and no lost baseline decision. The candidate made one definitive call among the 43 physician-indeterminate assignments, up from zero.

## What was tested

The archived DEFENSE-PFO registry (NCT01550588) excludes a participant for a nonvascular origin of the presenting neurological symptoms after brain imaging. The separate inclusion about a radiologically verified stroke has different evidence requirements. The shared contract for the assigned exclusion reads a post-imaging assessment. In the baseline, no extracted FHIR resource connected the stroke hospitalization to its CT and this contract returned unknown. [Archived registry](../../../nih_benchmark/round17/registry/benchmark_2015/xml/NCT01550588.xml)

In the original note for sigir-201515, line 0 documents hospitalization “for cryptogenic stroke two weeks ago.” Line 1 reads “At the time, computed tomography was negative for brain hemorrhage and she was given thrombolytic therapy with resolution of her symptoms.” The stroke diagnosis concerns a vascular event whose underlying cause is undetermined. That definition alone does not date the clinician's final attribution relative to this CT. [AHA/ASA secondary prevention guideline](https://doi.org/10.1161/STR.0000000000000375)

The candidate detected the linked diagnosis and completed imaging, checked the patient/episode context, and emitted one final Boolean Observation, `Observation/x-5eaa478286462d4d9f1135a85d65d3`. It set `neurologic_symptoms_nonvascular_origin_after_ct_or_mri` to false. The rule's outer NOT therefore returned MET. The source character intervals were [3,129) and [133,271), both measured in Unicode code points within the original note.

## Verification and correction

The predictor ran the usual FHIR screener on all 134 assignments and verified every trace through the public CLI. It wrote and hashed the predictions before the independent verifier opened the physician eligibility column. The freeze was `a8a2996fc684369f9bcd4b2d4d7a18168d9cc4aa8c89de4800c4688aa15786d0`; the score file was `59e39075e34d28fc9dd539795b83cab6ce66b2b1825c191e85994949ff26ab0b`. Only the one patient's chart and one criterion decision changed. [Frozen forecasts](../candidate_v2/freeze.json) · [Verified score and full delta](../evaluator/verified_v2/score.json)

A separate reviewer with no access to the score tested an admission diagnosis paired with a normal MRI, a completed CT, and a hemorrhage-negative CT. All three produced an unsupported definitive assessment. Conversely, a clinician explicitly assigning the symptoms to ischemic stroke after review of MRI yielded unknown. That pair of failures identifies the mismatch with the shared contract independently of the physician label. The corrective experiment records the source-linked clinical context separately from a final post-imaging attribution.

For reproduction, apply [the tested patch](02-tested-reader.patch) to an isolated copy of the supplied pipeline source, copy the prediction driver into its project-relative location, and run `python3.11 -B experiments/strict_evidence/predict.py /tmp/strict-reader-v2 --cli-check` from that copy. The original forecast freeze can be rescored using the evaluator and its digest above. No physician-selected passages, physician explanations or optional policy arms were used.
