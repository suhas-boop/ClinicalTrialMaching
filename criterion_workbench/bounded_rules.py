"""Versioned research bindings and deterministic predicates on a normalized FHIR snapshot."""

import calendar
import operator
import re
from copy import copy, deepcopy
from datetime import date

from compiler import digest, screen
from evidence import decision, instant, only_value


SOURCE_SHA256 = "9be767125b04fec06365f01b1db36805cd1059d4148b13342f43ee5a17b0ab4d"
FACTS = ("age", "ecog")
SCALAR = {"eq": operator.eq, "lt": operator.lt, "le": operator.le,
          "gt": operator.gt, "ge": operator.ge}
ID = re.compile(r"[A-Za-z0-9.-]{1,64}")


def approved_catalog(full_catalog=None, keys=None):
    """Select research bindings from the shipped catalog, allowing a local subset."""
    source = screen.CATALOG_DATA if full_catalog is None else full_catalog
    if digest(source) != SOURCE_SHA256:
        raise ValueError("Catalog differs from the supported four-study-r4 research catalog.")
    if keys is None:
        keys = FACTS
    if not isinstance(keys, (list, tuple, set, frozenset)) or any(
            not isinstance(key, str) or key not in FACTS for key in keys):
        raise ValueError("Only the age and ecog bindings are implemented.")
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate fact in catalog selection.")
    facts = {row["key"]: deepcopy(row) for row in source["mappings"] if row["key"] in keys}
    catalog = {"mode": "synthetic_research", "version": source["version"],
               "source_sha256": SOURCE_SHA256, "facts": facts}
    return {**catalog, "sha256": digest(catalog)}


def validate(expr, catalog):
    """Validate the whole expression and return the exact referenced binding keys."""
    if not isinstance(catalog, dict) or not isinstance(catalog.get("facts"), dict):
        raise ValueError("Supply an approved catalog selection.")
    if catalog != approved_catalog(keys=list(catalog["facts"])):
        raise ValueError("Binding definitions or catalog identity differ from the approved selection.")
    referenced = set()
    nodes = 0

    def visit(node, depth):
        nonlocal nodes
        nodes += 1
        if depth > 16 or nodes > 256:
            raise ValueError("Expression exceeds the supported tree size.")
        if not isinstance(node, dict):
            raise ValueError("A predicate or Boolean group is required.")
        if set(node) in ({"all"}, {"any"}):
            children = next(iter(node.values()))
            if not isinstance(children, list) or not 1 <= len(children) <= 256:
                raise ValueError("Boolean groups require a nonempty list of predicates.")
            for child in children:
                visit(child, depth + 1)
            return
        fact, op = node.get("fact"), node.get("op")
        if not isinstance(fact, str) or fact not in catalog["facts"]:
            raise ValueError("Fact has no approved binding in this catalog.")
        if not isinstance(op, str) or op not in (*SCALAR, "in"):
            raise ValueError("Unsupported comparison operator.")
        operand = "values" if op == "in" else "value"
        if set(node) != {"fact", "op", operand}:
            raise ValueError("Supply exactly the fields required by the comparison.")
        values = node[operand] if op == "in" else [node[operand]]
        if not isinstance(values, list) or not values:
            raise ValueError("A set comparison requires a nonempty list.")
        if any(type(v) is not int or v < 0 or (fact == "ecog" and v > 5) for v in values):
            raise ValueError("Threshold must be a nonnegative integer in the supported fact domain.")
        if len(set(values)) != len(values):
            raise ValueError("Duplicate comparison value.")
        referenced.add(fact)

    visit(expr, 0)
    return sorted(referenced)


def resource_id(value, kind):
    if isinstance(value, str):
        value = value.removeprefix(kind + "/")
        if ID.fullmatch(value):
            return value
    raise ValueError("Specify a logical " + kind + " ID.")


def ages_at_screen(chart):
    birth = chart.patient.get("birthDate")
    if not isinstance(birth, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", birth):
        raise ValueError("A complete Patient.birthDate is required.")
    born, day = date.fromisoformat(birth), chart.start.date()
    if born > day:
        raise ValueError("Birth date is after the screening date.")
    age = day.year - born.year - ((day.month, day.day) < (born.month, born.day))
    if (born.month, born.day) == (2, 29) and (day.month, day.day) == (2, 28) and not calendar.isleap(day.year):
        return (age, age + 1)
    return (age,)


def in_screen_scope(chart, resource):
    """Discard records proven outside the encounter before validating their clinical content."""
    if resource["resourceType"] != "Observation":
        return True
    if (resource.get("subject", {}).get("reference") != chart.person or
            resource.get("encounter", {}).get("reference") != chart.visit):
        return False
    for field, lower, upper in (("effectiveDateTime", chart.start, chart.end),
                                ("issued", None, chart.cutoff)):
        try:
            timestamp = instant(resource.get(field))
        except ValueError:
            continue  # The baseline reader rejects ambiguous time on a candidate record.
        if timestamp > upper or (lower is not None and timestamp < lower):
            return False
    return True


def score_at_screen(chart):
    scope = copy(chart)
    scope.resources = {key: item for key, item in chart.resources.items() if in_screen_scope(chart, item)}
    readings = scope.readings("ecog")
    evidence = list(chart.evidence)
    scores = set()
    for _, score, refs in readings:
        observation = chart.resources[refs[0].split("/_history/")[0]]
        only_value(observation, "valueInteger")
        if {key for key in observation if key.startswith("effective")} != {"effectiveDateTime"}:
            raise ValueError("Verify a single ECOG assessment timestamp.")
        evidence.extend(refs)
        scores.add(score)
    if len(scores) == 1:
        return scores.pop(), evidence, ""
    if scores:
        return None, evidence, "Resolve conflicting source-linked ECOG scores."
    return None, evidence, "Obtain a source-linked final ECOG score from the screening encounter."


def compare(node, value):
    if node["op"] == "in":
        return value in node["values"]
    return SCALAR[node["op"]](value, node["value"])


def evaluate(expr, catalog, bundle, patient, encounter, study, as_of):
    """Evaluate verified predicates as of an explicit offset-qualified screening instant."""
    facts = validate(expr, catalog)
    try:
        if not isinstance(study, str) or not study.strip():
            raise ValueError("Specify the screening study.")
        chart = screen.Snapshot(bundle, resource_id(patient, "Patient"), study,
                                resource_id(encounter, "Encounter"), as_of)
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        return decision("MISSING_DATA", "Verify the screening snapshot: " + str(error))

    values, reasons = {}, {}
    evidence = list(chart.evidence)
    for fact in facts:
        try:
            if fact == "age":
                values[fact] = ages_at_screen(chart)
            else:
                score, refs, reason = score_at_screen(chart)
                values[fact] = (score,)
                evidence.extend(refs)
                if reason:
                    reasons[fact] = reason
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            values[fact] = (None,)
            reasons[fact] = "Verify " + fact + " evidence: " + str(error)

    def walk(node, facts_at_screen):
        if "fact" in node:
            value = facts_at_screen[node["fact"]]
            return None if value is None else compare(node, value)
        group, children = next(iter(node.items()))
        results = [walk(child, facts_at_screen) for child in children]
        decisive = group == "any"
        if decisive in results:
            return decisive
        return None if None in results else not decisive

    available = {k: v[0] for k, v in values.items()}
    results = {walk(expr, {**available, "age": age}) for age in values.get("age", (None,))}
    if len(results) != 1:
        return decision("AUTHORING_HOLD", "Confirm the applicable leap-day birthday convention.", evidence)
    outcome = results.pop()
    if outcome is None:
        return decision("MISSING_DATA", " ".join(reasons.values()), evidence)
    state = "MET" if outcome else "NOT_MET"
    return decision(state, "The screening evidence satisfies the expression." if outcome
                    else "The screening evidence fails the expression.", evidence)
