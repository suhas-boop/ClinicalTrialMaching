"""Replay every assigned rule with TREC's exact, hash-pinned organizer summary as a second source.

Both documents are alternate descriptions of the same synthetic case. Neither summary
nor diagnosis wording gets promoted to extra firsthand observations or resolving grounds
for a conflict. For group topics both documents retain Group scope.
"""
import argparse
import base64
import collections
import copy
import json
from pathlib import Path
import sys
from source_join import digest, join, pinned, topic_index, PINS

STAMP = "2026-01-01T00:00:00Z"


def read(path):
    return json.loads(path.read_text())


def assert_summary_input(patient, frozen, source):
    year, number = patient[6:10], patient[10:]
    topic = source[year][number]
    summary = topic.findtext("summary")
    if not summary or digest(topic.findtext("description").encode()) != frozen["description_sha256"]:
        raise ValueError("Summary and authenticated description do not match")
    return dict(summary=summary, summary_sha256=digest(summary.encode()), subject_id=patient,
                topic=number, year=year, locator=f"/topics/topic[@number='{number}']/summary",
                xml_sha256=PINS[f"{year}.xml"],
                source_url="https://trec-cds.org/" + ("topics2014.xml" if year == "2014" else "topics2015A.xml"))


def run(root):
    sys.path.insert(0, str(root / "round14"))
    from record_arrivals import receive, evaluate
    from screen import screen, verify
    frozen = join(root)
    source = {year: topic_index(pinned(root / "round7" / f"{year}.xml")) for year in ("2014", "2015")}
    notes = read(root / "round9/notes.json")
    assignments = read(root / "round9/assignments.json")
    subjects = {r["case"]: r["subject"] for r in read(root / "round9/export/cases.json")}
    pack = verify(read(root / "round11/compiled.json"))
    manual = {
        "sigir-20157": "Original description gives age 20 and summary gives 22. Both sources describe symptoms. Neither contains a unipolar major depressive disorder diagnosis.",
        "sigir-20141": "Summary calls chest pain exercise-related; it supplies neither severity of hypertension nor a creatinine result.",
        "sigir-201411": "Summary says hypotension but gives no heart or respiratory rate, PaCO2 value, or formal shock diagnosis.",
        "sigir-201415": "Summary calls a reported ultrasound compatible with vesicular mole or fibroid degeneration. Neither possible diagnosis documents menopause.",
        "sigir-201421": "Summary restates positive ANA and anti-double-stranded DNA and butterfly-shaped rash, without a specific diagnosis.",
        "sigir-201423": "Hyperinflation, smoking and oxygen requirement do not establish a GOLD-classified COPD exacerbation.",
        "sigir-201424": "Ruptured spleen and intraperitoneal hemorrhage do not document that an emergency laparotomy actually took place.",
        "sigir-201425": "The summary adds helmet nonuse. The full note gives GCS 6/15 but defers CT. The summary supplies neither the absent imaging result nor an explicit exclusion of a second vehicle or rider.",
        "sigir-201426": "Wording describes a group including three pregnant women. It does not identify a screened individual.",
        "sigir-20151": "Summary explicitly adds hypoxia to the signs given for this synthetic patient. No numerical oxygenation value is provided.",
        "sigir-201510": "Names dysmenorrhea, menorrhagia and menometrorrhagia explicitly. The note reports painful and heavy irregular menses and spotting. Neither provides the rule quantifier for the symptom list or documents dyspareunia.",
        "sigir-201430": "Adds medication compliance to the worsening hypertension history. Cardiac severity and its required definition remain open.",
        "sigir-201517": "Specifies positive HPV screening with normal cytology. The required APTIMA instrument, version and qualifying aliquot remain unestablished.",
        "sigir-201519": "Unintentional weight loss appears in the summary only. This subject has no assigned rule.",
        "sigir-201520": "Memory and personality changes do not supply a cognitive screening result at admission.",
        "sigir-201523": "Blood counts are abnormal during the current encounter. The summary does not date a prior blood dyscrasia.",
    }
    cases = []
    sources = {}
    assigned = collections.defaultdict(list)
    for assignment in assignments:
        assigned[assignment["patient"]].append(assignment)
    for patient, frozen_record in frozen.items():
        entry = assert_summary_input(patient, frozen_record, source)
        summary = entry["summary"]
        subject = subjects[patient]
        visit = "same-case-" + patient
        doc_id = patient + "-trec-summary"
        case_ids = [str(a["annotation_id"]) for a in assigned[patient]]
        entry.update(subject=subject, assigned=case_ids)
        if patient in manual:
            entry["review_note"] = manual[patient]
        if subject.startswith("Group/"):
            group_bundle = read(root / "round9/export/bundles" / (patient + ".json"))
            original = [e["resource"] for e in group_bundle["entry"]]
            original_source = next(r for r in original if r["resourceType"] == "DocumentReference")
            if original_source["subject"]["reference"] != subject:
                raise ValueError("Mismatched Group")
            # Group data must never go through the patient-only intake. Make a new,
            # group-scoped source view of both texts and use the ordinary scope guard.
            group_view = copy.deepcopy(original)
            group_doc = next(r for r in group_view if r["resourceType"] == "DocumentReference")
            rendered = notes[patient] + "\n" + summary
            group_doc["identifier"] = [{"system": "urn:pocketmd:sha256", "value": digest(rendered.encode())}]
            group_doc["content"][0]["attachment"]["data"] = base64.b64encode(rendered.encode()).decode()
            entry.update(source_resource_type="Group", added_source_digest=entry["summary_sha256"],
                         separately_ingested_clinical_facts=[])
        else:
            original = receive(patient, visit, patient + "-note", notes[patient], STAMP)
            second = receive(patient, visit, doc_id, summary, STAMP)
            source_doc = next(r for r in second if r["resourceType"] == "DocumentReference")
            attachment = source_doc["content"][0]["attachment"]
            if base64.b64decode(attachment["data"], validate=True).decode() != summary:
                raise ValueError("Supplementary summary changed on intake")
            entry.update(source_resource_type="Patient", added_source_digest=entry["summary_sha256"],
                         separately_ingested_clinical_facts=[{"resource": r["resourceType"] + "/" + r["id"],
                             "concept": r.get("code", r.get("medicationCodeableConcept")),
                             "value": {k: v for k,v in r.items() if k.startswith("value")}}
                            for r in second if r["resourceType"] in ("Condition", "Observation", "MedicationStatement")])
        sources[patient] = entry
        for a in assigned[patient]:
            key = str(a["annotation_id"])
            if subject.startswith("Group/"):
                old_trace = screen(original, subject, pack, a["study"], key)
                new_trace = screen(group_view, subject, pack, a["study"], key)
                if old_trace["source_sha256"] == new_trace["source_sha256"]:
                    raise ValueError("Same-scope group summary was not read")
                if new_trace["criteria"][key]["evidence"]:
                    raise ValueError("Unexpected individual evidence from Group")
            else:
                old_trace = evaluate(original, patient, visit, pack, a["study"], [key])
                new_trace = evaluate(original + second, patient, visit, pack, a["study"], [key])
                if old_trace["snapshot_sha256"] == new_trace["snapshot_sha256"]:
                    raise ValueError("Summary did not enter the chart snapshot")
            old, new = old_trace["criteria"][key], new_trace["criteria"][key]
            before = {k:[v["state"],v.get("value")] for k,v in old["facts"].items()}
            after = {k:[v["state"],v.get("value")] for k,v in new["facts"].items()}
            changes = {k:[before.get(k),after.get(k)] for k in before.keys() | after.keys() if before.get(k)!=after.get(k)}
            cited = {k:v for k,v in new.get("locations",{}).items() if v["document"] == "DocumentReference/" + doc_id}
            cases.append(dict(case=key, subject=subject, study=a["study"], baseline=old["state"],
                              with_summary=new["state"], changed_facts=changes, summary_evidence=cited))
    if len(sources) != 53 or len(cases) != 134 or len({r["case"] for r in cases}) != len(cases):
        raise ValueError("Unexpected frozen inventory")
    return {
        "notes_joined": len(frozen), "subjects_with_assignments": sum(bool(row["assigned"]) for row in sources.values()),
        "subjects_without_assignments": [p for p in sources if not sources[p]["assigned"]],
        "group_assignments": sum(r["subject"].startswith("Group/") for r in cases),
        "rule_pairs": len(cases), "changed_outcomes": [r["case"] for r in cases if r["baseline"] != r["with_summary"]],
        "changed_operands": [r["case"] for r in cases if r["changed_facts"]],
        "summary_cited_by_rule": [r["case"] for r in cases if r["summary_evidence"]],
        "baseline_outcomes": dict(collections.Counter(r["baseline"] for r in cases)),
        "expanded_outcomes": dict(collections.Counter(r["with_summary"] for r in cases)),
        "subjects": sources, "cases": cases,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.benchmark)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k:v for k,v in report.items() if k not in ("subjects", "cases")}, indent=2))
