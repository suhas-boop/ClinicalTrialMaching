# TrialGPT source roles

NIH's `run_matching.py` [appends a standard sentence to each patient vignette](https://github.com/ncbi-nlp/TrialGPT/blob/97ba047695ca77bfe8d3634c10cbe10b0095929f/trialgpt_matching/run_matching.py#L28-L35) before passing it to the matching model. That sentence supplies a benchmark assumption about future consent and practical compliance. It provides no patient-specific record of those facts.

The evidence-score command ingests the frozen source with the TrialGPT profile. The profile checks the subject, SHA-256 of the complete note, the pinned manifest and the appended text. It retains the original attachment and character offsets. A DocumentReference extension identifies the sentence's origin, and the export omits assertions derived from the appended sentence. Other patient evidence can still support consent criteria according to their precise wording.

`python -B pocketmd.py fhir-convert DESTINATION` rebuilds all 53 benchmark bundles. For an individual frozen note, supply `--note FILE --patient SUBJECT --frozen-trialgpt`. Ordinary single-note imports keep their usual source interpretation, including identical words in a different clinical document.

Previously exported FHIR bundles retain their original resources. Rebuild a benchmark export before screening it. Arbitrary uploaded bundles carry their own provenance and cannot be assumed to have gone through this verified import. The benchmark contains 134 scored assignments involving 44 distinct subjects. The fresh source-role pass preserves all six strict decisions.
