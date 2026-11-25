"""Join published organizer diagnoses to exactly matched, synthetic TREC-SIGIR vignettes.

Offline and independent of trial IDs, expected eligibility, matching results, or clinician
annotations. Return supplemental research-source FHIR documents without promoting any
surface wording to a coded condition, disease subtype, clinical confirmation or onset.
"""
import argparse
import base64
import hashlib
import html
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
BASE = "https://trec-cds.org/"
PINS = {
    "2014.xml": "8fa33d3a258da436c05d6009fc5713cc56038cc488535e52eccd6c19a11fc9e9",
    "2015.xml": "511f8992b7b2676a14a14cf556b2995a1084004691f2e7c031151d3eeac4e59c",
    "topics2015B.xml": "7bc4bbe801f9d1ada3574aa7be5a8b0ccd20594a957f6feda38f378e93ff67ee",
    "track2015.html": "2c64eda9900fed3f0c09f269dfad41ae4f50c1c1af3321bc8e137869af130f69",
}
BOILERPLATE = "The patient will provide informed consent, and will comply with the trial protocol without any practical issues."


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pinned(path):
    data = path.read_bytes()
    if digest(data) != PINS[path.name]:
        raise ValueError(f"Source changed: {path.name}")
    return data


def normalized(text):
    return " ".join(text.split())


def frozen_description(note):
    sentences = note.splitlines()
    cleaned = []
    for n, sentence in enumerate(sentences):
        prefix = f"{n}. "
        if not sentence.startswith(prefix):
            raise ValueError("Unrecognized sentence numbering")
        cleaned.append(sentence[len(prefix):])
    if cleaned[-1] != BOILERPLATE:
        raise ValueError("Unrecognized final sentence")
    return normalized(" ".join(cleaned[:-1]))


def description_match(frozen, original):
    if normalized(original) == frozen:
        return "equal after whitespace and source formatting"
    if re.sub(r"(?<=\d)°(?=[FC]\b)", "", normalized(original)) == frozen:
        return "equal after formatting and temperature degree-symbol normalization"
    raise ValueError("Source subject and note content do not match")


def topic_index(data):
    index = {}
    for topic in ET.fromstring(data).findall("topic"):
        number = topic.attrib["number"]
        if number in index:
            raise ValueError(f"Duplicate topic {number}")
        index[number] = topic
    return index


def organizer_example(data, topic):
    doc = normalized(re.sub(r"<[^>]+>", " ", html.unescape(data.decode())))
    summary = normalized(topic.findtext("summary"))
    if doc.count(summary) != 1 or doc.count('the diagnosis of the treatment topic above is "lupus".') != 1:
        raise ValueError("Official example and diagnosis locator do not resolve uniquely")
    return "lupus"


def supplemental_record(patient, diagnosis, locator, url, source_hash):
    record_id = f"{patient}-trec-diagnosis"
    fhir = {
        "resourceType": "DocumentReference", "id": record_id,
        "status": "current", "subject": {"reference": "Patient/" + patient},
        "type": {"text": "TREC organizer-supplied synthetic vignette diagnosis"},
        "description": "Supplemental research-source diagnosis",
        "content": [{"attachment": {
            "contentType": "text/plain", "data": base64.b64encode(diagnosis.encode()).decode(),
            "title": locator,
        }}],
        "context": {"related": [{"identifier": {"system": url, "value": source_hash}}]},
    }
    return {"wording": diagnosis, "locator": locator, "source_url": url,
            "source_sha256": source_hash, "fhir": fhir}


def join(benchmark, source_dir=HERE):
    a = {year: topic_index(pinned(benchmark / "round7" / f"{year}.xml")) for year in ("2014", "2015")}
    b = topic_index(pinned(source_dir / "topics2015B.xml"))
    example = pinned(source_dir / "track2015.html")
    notes = json.loads((benchmark / "round9/notes.json").read_text())
    hashes = json.loads((benchmark / "round9/note_hashes.json").read_text())
    if set(notes) != set(hashes):
        raise ValueError("Frozen note inventory does not match its manifest")
    records = {}
    for patient, note in notes.items():
        match = re.fullmatch(r"sigir-(201[45])([1-9]\d?)", patient)
        if not match or digest(note.encode()) != hashes[patient]:
            raise ValueError(f"Invalid subject identifier or checksum: {patient}")
        year, number = match.groups()
        topic = a[year][number]
        original = topic.findtext("description")
        joined = description_match(frozen_description(note), original)
        extra = None
        if year == "2015":
            task_b = b[number]
            if any(task_b.findtext(key) != topic.findtext(key) for key in ("description", "summary")) or task_b.get("type") != topic.get("type"):
                raise ValueError(f"Task B subject mismatch for {patient}")
            diagnosis = task_b.findtext("diagnosis")
            if diagnosis:
                extra = supplemental_record(patient, diagnosis.strip(), f"/topics/topic[@number='{number}']/diagnosis",
                                            BASE + "topics2015B.xml", PINS["topics2015B.xml"])
        elif year == "2014" and number == "21":
            diagnosis = organizer_example(example, topic)
            extra = supplemental_record(patient, diagnosis,
                                        "Example treatment topic, paragraph immediately after examples table",
                                        BASE + "2015.html", PINS["track2015.html"])
        records[patient] = {"source_note_sha256": hashes[patient], "same_case_check": joined,
                            "description_sha256": digest(original.encode()), "supplement": extra}
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark", type=Path, help="nih_benchmark directory of the PocketMD freeze")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    records = join(args.benchmark)
    args.out.write_text(json.dumps(records, indent=2) + "\n")
    print(json.dumps({"notes_matched": len(records),
                      "supplemental_diagnoses": sum(bool(row["supplement"]) for row in records.values())}))
