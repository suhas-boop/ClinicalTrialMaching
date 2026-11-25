"""Evaluate a reviewed bounded rule against an independently supplied scalar fact row."""
import math
import sys
from pathlib import Path


WORKBENCH = Path(__file__).resolve().parents[3] / "criterion_workbench"
sys.path.insert(0, str(WORKBENCH))
import bounded_rules
import rules


def checked_expression(rule):
    if rule["format"] != rules.FORM or rule["sha256"] != rules.digest(
        {key: value for key, value in rule.items() if key != "sha256"}
    ):
        raise ValueError("Invalid exported rule format or checksum")
    catalog = rules.trusted_catalog(rule["catalog"])
    bindings = bounded_rules.validate(rule["expression"], catalog)
    review = rule["authoring_review"]
    if (bindings != rule["bindings"] or review["status"] != rules.READY
            or review["expression"] != rule["expression"] or review["questions"] or review["gaps"]):
        raise ValueError("Expected an executable export and matching bindings")
    return rule["expression"], bindings


def scalar_value(key, value):
    if value is None:
        return None
    if type(value) is float:
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError(f"{key} must be recorded in whole units")
        value = int(value)
    if type(value) is not int or value < 0 or (key == "ecog" and value > 5):
        raise ValueError(f"{key} is outside the selected integer fact domain")
    return value


def evaluate(expression, facts):
    if "fact" in expression:
        value = scalar_value(expression["fact"], facts.get(expression["fact"]))
        return None if value is None else bounded_rules.compare(expression, value)
    group, children = next(iter(expression.items()))
    results = [evaluate(child, facts) for child in children]
    decisive = group == "any"
    if decisive in results:
        return decisive
    return None if None in results else not decisive


def screen(rule, facts, source_ref):
    expression, bindings = checked_expression(rule)
    outcome = evaluate(expression, facts)
    evidence = [f"{source_ref}/{key}" for key in bindings]
    state, reason = {
        True: ("MET", "The normalized facts satisfy the expression."),
        False: ("NOT_MET", "The normalized facts fail the expression."),
        None: ("MISSING_DATA", "A required normalized fact is unavailable."),
    }[outcome]
    return {"rule_sha256": rule["sha256"], "state": state, "reason": reason, "evidence": evidence}
