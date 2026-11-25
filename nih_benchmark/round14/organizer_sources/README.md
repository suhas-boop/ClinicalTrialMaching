# Matched supplementary public case material

This secondary, expanded-source evaluation uses the organizer's published TREC diagnoses. The frozen TrialGPT narratives and eligibility benchmark keep their original definitions.

## Reproduction

From this directory, use the benchmark's existing nih_benchmark directory as the argument.

```sh
python source_join.py /path/to/nih_benchmark --out manifest.json
python replay.py /path/to/nih_benchmark --out replay.json
python test_join.py /path/to/nih_benchmark -v
```

The scripts use offline inputs. The 2014 and 2015 Task A descriptions and frozen note hashes are already distributed with the benchmark. Two additional organizer source files are hash-pinned here. The join checks the subject ID, narrative text and frozen note hash. It strips sentence numbering and the standard TrialGPT closing sentence. Whitespace is collapsed. Exactly one note omits degree signs before Celsius and Fahrenheit. For every joined 2015 topic the descriptions, summaries and topic types in Task A and Task B agree exactly after parsing XML. The source join reads no trial IDs, eligibility outcomes or reviewer annotations.

## Result

All 53 available frozen notes matched their corresponding organizer narratives. The TREC 2015 Task B XML contributed 14 diagnosis fields. One official organizer example in the 2015 guidance independently contributed the literal diagnosis “lupus” for 2014 topic 21. Its summary matches 2014 topic 21 exactly. Two supplement-bearing patients had no rule assignments. The other 13 had 41 assigned cases.

The three arms were the frozen note, the frozen note plus a separate FHIR document, and a provenance-linked combined document containing the exact diagnosis wording. The current frozen matcher indexes one canonical note. Attaching the additional document alone produced the same input hash. In the combined arm, the existing intake and normal screen call consumed a different source hash for every assigned case. One standard-coded hypothyroidism Condition was extracted. Its case assignments asked about previous thyroid treatments, surgery, radiation or tests. No clinical operand or eligibility state changed in the 41 assigned cases. A raw diagnosis field can add source information even where it cannot satisfy a rule operand.

Generic lupus left case 414 missing. In separate controls for that same executable criterion, an explicit systemic lupus erythematosus assertion produced MET and explicit negation produced NOT_MET. Six test methods passed, including source integrity, subject/units/comparator checks and the three subtype controls. The external paper that mentions systemic lupus for this case labels that entry a Wiki-DP prediction in Figure 4.

## Sources

- [TREC 2014 task and topic field specification](https://trec-cds.org/2014.html)
- [TREC 2015 task and organizer's lupus example](https://trec-cds.org/2015.html)
- [TREC 2015 Task B source XML](https://trec-cds.org/topics2015B.xml)
- [Zhang and He, caption for Figure 4](https://d-scholarship.pitt.edu/32402/1/camera-ready.pdf)
