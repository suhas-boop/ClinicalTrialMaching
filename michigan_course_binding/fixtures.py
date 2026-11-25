"""Write deliberately structured synthetic chart data to R4; no eligibility labels in resources."""
RX = "http://www.nlm.nih.gov/research/umls/rxnorm"
LOCAL = "urn:pocketmd:research:course-binding-fixture"
DATE = "2026-04-15"


def ref(path):
    return {"reference": path}


def code(system, value):
    return {"coding": [{"system": system, "code": value}]}


def make(case, prefix):
    base = prefix + case["id"]
    rows = []

    def add(kind, suffix, **fields):
        ident = base + "-" + suffix
        path = kind + "/" + ident
        rows.append({"resource": dict(fields, id=ident, resourceType=kind),
                     "request": {"method": "PUT", "url": path}})
        return path

    patient = ref(add("Patient", "p", active=True))
    courses = {}
    for role, description in [("current", "Advanced LMS episode"), ("prior", "Prior localized LMS episode")]:
        condition = ref(add("Condition", role, subject=patient, code={"text": description}))
        period = {"start": "2026-04-01"} if role=="current" else {"start":"2026-01-01","end":"2026-04-01"}
        courses[role] = ref(add("CarePlan", role, status="active" if role=="current" else "completed",
                                intent="plan", subject=patient, addresses=[condition], period=period))

    for name, dtype, value in [("treatment-line", "valueInteger", case.get("line",1)),
                               ("complete-course-medication-inventory", "valueBoolean", case.get("complete",True))]:
        if value is not None:
            add("Observation", "line" if dtype=="valueInteger" else "inventory", status="final", subject=patient, code=code(LOCAL,name),
                focus=[courses["current"]], effectiveDateTime=DATE, **{dtype:value})

    if case.get("receiving", True):
        add("Observation","on-treatment", status="final", subject=patient, code=code(LOCAL,"course-receiving"),
            focus=[courses["current"]], effectiveDateTime=DATE, valueBoolean=True)
    if "regimen_name" in case:
        add("Observation","named-regimen", status="final", subject=patient, code=code(LOCAL,"documented-current-regimen"),
            focus=[courses["current"]], effectiveDateTime=DATE, valueString=case["regimen_name"])

    for i,(product,course,*modes) in enumerate(case["meds"]):
        mode = modes[0] if modes else "given"
        medication=code(RX if product.isdigit() else LOCAL,product)
        fields=dict(subject=patient,medicationCodeableConcept=medication,authoredOn="2026-04-01",
                    status="active",intent="order")
        if course:
            fields["basedOn"]=[courses[course]]
        order=add("MedicationRequest",str(i),**fields)
        if mode != "order":
            add("MedicationAdministration",str(i),subject=patient,medicationCodeableConcept=medication,
                effectiveDateTime="2026-04-18" if mode=="future" else "2026-04-01",
                request=ref(order),status="not-done" if mode=="not-done" else "completed")
    return rows
