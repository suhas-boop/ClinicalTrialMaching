# First stroke reader, rejected before scoring

The R18 continuation checkpoint and R21 reconcile replay both retain the six strict baseline decisions. The prior alternate-note/organizer audit already covered the 44 assigned subjects. Its source comparisons yielded no additional strict criterion outcome. This experiment used their original notes and did not repeat that search.

Review of the 134 blind baseline traces identified case 817. The original note explicitly names a cryptogenic stroke hospitalization and ties the subsequent sentence about cranial imaging to that hospitalization. The baseline had no relevant FHIR fact on either line. The existing catalog already accepts a final post-imaging assessment of whether the neurological symptoms were nonvascular. The normal screen negates that fact for the exclusion.

A first shared reader recognized the two linked assertions. All 134 CLI comparisons matched the in-process screener. Case 817 alone changed, from MISSING_DATA to MET. Code review rejected the reader before physician scoring because its handling of unrelated trailing material depended on narrow, cardiology-specific sentence shapes. This outcome guided a replacement based on event scope and subject consistency. Patient identifiers and trial IDs had no role in extraction.

The baseline freeze SHA-256 is `88d1fd3fe4b48699b9a00c55aa64394a97657503db92b464f3308b2f6b485627`. The first candidate freeze is `4aab2fb4eb3bbc5a790c86de76cae280b963d3e2e0237b3b7ab925e04d852336`. To reproduce this version, apply 01-initial-reader.patch to an isolated copy of the supplied pipeline archive, copy the prediction driver to experiments/strict_evidence/predict.py there, and run the following command from that copy.

```sh
python3.11 -B experiments/strict_evidence/predict.py /tmp/strict-reader-v1 --cli-check
```
