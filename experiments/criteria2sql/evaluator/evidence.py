"""Audit the independent flat and FHIR inputs to the synthetic age comparison."""
from datetime import date, datetime, timezone


def completed_years(birth, day):
    return day.year - birth.year - ((day.month, day.day) < (birth.month, birth.day))


def inspect_evidence(row, chart, bundle, fhir_result):
    patient_id = row["patient_id"]
    patient_ref = f"Patient/{patient_id}"
    resources = [entry["resource"] for entry in bundle["entry"]]
    patients = [r for r in resources if r["resourceType"] == "Patient" and r["id"] == patient_id]
    visits = [r for r in resources if r["resourceType"] == "Encounter" and
              r["subject"]["reference"] == patient_ref]
    if len(patients) != 1 or len(visits) != 1:
        raise ValueError(f"{patient_id} needs exactly one linked patient and screening encounter")
    patient, encounter = patients[0], visits[0]
    if (patient.get("birthDate"), encounter["period"]["start"]) != (chart["birth_date"], chart["screening_start"]):
        raise ValueError(f"Bundle differs from source chart for {patient_id}")
    if (row["id"], row["scope"]) != (chart["id"], chart["scope"]):
        raise ValueError(f"Input identity or scope differs for {patient_id}")
    start = datetime.fromisoformat(chart["screening_start"])
    cutoff = datetime.fromisoformat(chart["as_of"])
    if start.tzinfo is None or cutoff.tzinfo is None or start > cutoff:
        raise ValueError(f"Invalid synthetic screening window for {patient_id}")
    if fhir_result["patient"] != patient_id or fhir_result["encounter"] != encounter["id"] or fhir_result["as_of"] != chart["as_of"]:
        raise ValueError(f"Decision points to another chart or snapshot for {patient_id}")
    if (encounter["status"] != "in-progress" or
            {"system": "urn:pocketmd:demo:screening-study", "value": fhir_result["study"]} not in encounter["identifier"]):
        raise ValueError(f"Encounter study or status mismatch for {patient_id}")
    source_urn = f"urn:pocketmd:criteria2sql:synthetic-controls-v1:chart:{row['id']}"
    refs = []
    for resource in (patient, encounter):
        meta = resource["meta"]
        updated = datetime.fromisoformat(meta["lastUpdated"].replace("Z", "+00:00"))
        if updated > cutoff or not meta["versionId"] or meta["source"] != source_urn:
            raise ValueError(f"Unversioned or unavailable resource at cutoff for {patient_id}")
        refs.append(f"{resource['resourceType']}/{resource['id']}/_history/{meta['versionId']}")
    birth = date.fromisoformat(patient["birthDate"]) if "birthDate" in patient else None
    age = completed_years(birth, start.date()) if birth else None
    if row["age"] != age or (row["scope"] == "complete") != (age is not None):
        raise ValueError(f"Source age or completeness conflict for {patient_id}")
    cited = set(fhir_result["evidence"])
    return {
        "birth_date": chart["birth_date"], "screening_start": chart["screening_start"],
        "as_of": chart["as_of"], "screening_local_age": age,
        "age_if_cutoff_used": completed_years(birth, cutoff.date()) if birth else None,
        "age_if_utc_screen_date_used": completed_years(birth, start.astimezone(timezone.utc).date()) if birth else None,
        "chart_source": source_urn, "source_references": refs, "decision_evidence": sorted(cited),
        "source_references_in_decision": set(refs).issubset(cited),
    }
