"""Deterministic, scoped prototype over a patient-scoped FHIR R4 readback."""
from urllib.parse import urlencode
from fixtures import LOCAL


def key(r):
    return r["resourceType"]+"/"+r["id"]


def versioned(r):
    return key(r)+"/_history/"+r["meta"]["versionId"]


def links(r, field):
    return [x.get("reference") for x in r.get(field, [])]


def search(api, kind, patient, trace):
    path = kind+"?"+urlencode({"patient":patient, "_count":2})
    resources=[]
    while path:
        trace.append(path)
        bundle=api.call(path)
        assert bundle["type"]=="searchset"
        for e in bundle.get("entry", []):
            if e.get("search",{}).get("mode","match")=="match":
                r=e["resource"]
                assert r["resourceType"]==kind and r["subject"]["reference"]==patient
                resources.append(r)
        path=next((p["url"] for p in bundle.get("link",[]) if p["relation"]=="next"),None)
    return resources


def active_ingredients(product):
    """Accept a verified complete list, including legacy single-ingredient entries."""
    if not isinstance(product, dict):
        return ()
    values = product.get("ingredients", [product.get("ingredient")])
    if not isinstance(values, list) or not values:
        return ()
    if not all(isinstance(value, str) and value.strip() for value in values):
        return ()
    if "ingredient" in product and set(values) != {product["ingredient"]}:
        return ()
    return tuple(dict.fromkeys(values))


def evaluate(api, patient, episode, day, catalog):
    rule=catalog["rule"]
    trace={"queries":[],"evidence":[],"medications":[],"as_of":day,"patient":patient,"episode":episode}
    def result(outcome, reason):
        return dict(trace,outcome=outcome,reason=reason)
    dx=api.call(episode)
    assert dx["subject"]["reference"]==patient
    trace["evidence"].append(versioned(dx))
    data={kind:search(api,kind,patient,trace["queries"]) for kind in
          ("CarePlan","Observation","MedicationRequest","MedicationAdministration")}
    courses=[r for r in data["CarePlan"] if r["status"]=="active" and episode in links(r,"addresses")
             and r["period"]["start"]<=day<=r["period"].get("end",day)]
    if len(courses)!=1:
        return result("MISSING_DATA","Identify the active course for this disease episode.")
    course=courses[0]
    trace["evidence"].append(versioned(course))
    facts={}
    for r in data["Observation"]:
        if key(course) not in links(r,"focus") or r["status"]!="final" or r["effectiveDateTime"]>day:
            continue
        for c in r["code"]["coding"]:
            if c["system"]==LOCAL:
                facts.setdefault(c["code"],[]).append(r)
                trace["evidence"].append(versioned(r))
    def fact(name,field):
        values={r.get(field) for r in facts.get(name,[])}
        return values.pop() if len(values)==1 else None
    line=fact("treatment-line","valueInteger")
    complete=fact("complete-course-medication-inventory","valueBoolean") is True
    orders={key(r):r for r in data["MedicationRequest"] if r["status"]!="entered-in-error"}
    given=set()
    ingredients=set()
    unlinked=False
    review_form=False
    unmapped=False
    has_current_dose=False
    for r in data["MedicationAdministration"]:
        order=orders.get(r.get("request",{}).get("reference"))
        if order:
            given.add(key(order))
        if r["status"]!="completed" or r["effectiveDateTime"]>day:
            continue
        item={"administration":versioned(r),"order":versioned(order) if order else None,
              "course_links":links(order,"basedOn") if order else [],
              "product":r["medicationCodeableConcept"]["coding"]}
        trace["medications"].append(item)
        if len(item["course_links"])!=1:
            unlinked=True
            item["binding"]="unresolved course"
            continue
        if key(course) not in item["course_links"]:
            item["binding"]="other course"
            continue
        if r["effectiveDateTime"]<course["period"]["start"]:
            unlinked=True
            item["binding"]="outside course period"
            continue
        codes={c["code"] for c in item["product"] if c["system"]==catalog["system"]}
        mapped=catalog["products"].get(next(iter(codes))) if len(codes)==1 else None
        has_current_dose=True
        components = active_ingredients(mapped)
        if not components:
            unmapped=True
            item["binding"]="terminology unresolved"
            continue
        item.update(ingredients=list(components), formulation=mapped.get("formulation"), binding="current course")
        if len(components) == 1:
            item["ingredient"] = components[0]
        ingredients.update(component for component in components if component != rule["ingredient"])
        if rule["ingredient"] in components:
            if mapped.get("formulation") in rule["tested_formulations"]:
                ingredients.add(rule["ingredient"])
            else:
                review_form = True
    planned=[r for rid,r in orders.items() if rid not in given and links(r,"basedOn")==[key(course)]
             and r["status"]=="active" and r["intent"]=="order" and r["authoredOn"]<=day]
    trace["orders_without_administration"]=[versioned(r) for r in planned]
    receiving=fact("course-receiving","valueBoolean") is True
    named=fact("documented-current-regimen","valueString")
    if receiving and has_current_dose and line is not None and line!=rule["line"]:
        return result("NOT_MET","Documented line for the receiving course fails the first-line requirement.")
    if receiving and has_current_dose and line==rule["line"] and (rule["ingredient"] in ingredients or
            set(rule["alternative_combination"]).issubset(ingredients)):
        return result("MET","Qualifying components, treatment line and administration bind to the same current course.")
    if named and not has_current_dose:
        components=catalog["regimen_names"].get(named)
        trace["named_regimen"]={"reported":named,"components":components,"source":catalog["regimen_source"] if components else None}
        if components is None:
            return result("BINDING_HOLD","Resolve the site regimen name to a verified component listing.")
        return result("MISSING_DATA","Named regimen supplies candidate components. Obtain product/formulation and check patient-specific modifications.")
    if review_form:
        return result("AUTHORING_HOLD","Does this protocol accept the documented formulation of doxorubicin?")
    if unmapped:
        return result("BINDING_HOLD","Verify product terminology before classifying the regimen.")
    ordered_products={c["code"] for r in planned for c in r["medicationCodeableConcept"]["coding"]
                      if c["system"]==catalog["system"]}
    ordered_ingredients = {ingredient for product in ordered_products
                           for ingredient in active_ingredients(catalog["products"].get(product))}
    qualifying_order=(rule["ingredient"] in ordered_ingredients or set(rule["alternative_combination"])<=ordered_ingredients)
    if qualifying_order and not has_current_dose:
        return result("AUTHORING_HOLD","MI-TX-STATE: qualifying therapy ordered only; planned-only meaning requires review.")
    if unlinked or not has_current_dose or not receiving or line is None or not complete or planned:
        return result("MISSING_DATA","Resolve the missing course link, qualifying administration, line or full regimen inventory.")
    return result("NOT_MET","The attested complete current regimen has neither accepted alternative.")
