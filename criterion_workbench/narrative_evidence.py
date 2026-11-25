"""Read narrowly defined patient facts from a numbered screening vignette.

This adapter is for a single narrative used as the screening snapshot. It does
not transfer a historical or relative's age to a later trial encounter.
"""
import argparse
import json
import re
from vital_measurements import measurements
from pathlib import Path

AGE = re.compile(r"^(?:A|An|The patient is a|The patient is an)\s+(\d{1,3})(?:[- ]year[- ]old|\s+yo)\b",re.I)
GROUP = re.compile(r"^(?:(?:a|the)\s+group\b|(?:a|the)\s+(?:family|couple)\s+of\b|\d+\s+(?:patients|people|participants)\b)",re.I)
LINES = re.compile(r"^(\d+)\. (.+)$")

def extract(note):
    """Return source-linked values and scope warnings. Unrecognised statements yield no fact."""
    lines = {}
    for line in note.strip().splitlines():
        match=LINES.fullmatch(line)
        if not match or int(match[1]) in lines:
            raise ValueError("Expected unique numbered source sentences.")
        lines[int(match[1])]=match[2]
    if not lines or sorted(lines)!=list(range(len(lines))):
        raise ValueError("Missing source sentence or nonzero first sentence.")
    first=lines[0]
    if GROUP.match(first):
        return {"scope":"multiple_subjects","facts":{}}
    facts=measurements(lines)
    match=AGE.match(first)
    if match and 0<=int(match[1])<=125:
        suffix=first[match.end():]
        # Only accept an explicit patient presentation in the same main clause.
        # A relative or a historical/negated introduction is never patient-age evidence.
        subject=re.match(r"^\s+((?:[\w-]+\s+){0,5})(?:presents?\b|presented\b|is (?:brought|evaluated|found)\b|comes\b|complains\b|undergoes\b|with\b)",suffix,re.I)
        if subject and not re.search(r"\b(?:mother|father|sister|brother|son|daughter|caregiver|spouse|formerly|previously|then|not|when|was)\b",subject[0],re.I):
            facts['age_years']={"value":int(match[1]),"sentences":[0],"quote":first}
    return {"scope":"individual_or_unspecified","facts":facts}

def supports(key,spec):
    if key in {"heart_rate","respiratory_rate"}:
        return (spec.get("role")=="record" and spec.get("kind")=="number" and
                spec.get("unit")=="/min" and spec.get("scope")==key.replace("_"," "))
    return (key=='age_years'  and spec.get('kind')=='number' and spec.get('unit')=='a' and
            spec.get('role')=='record' and spec.get('scope')=='age years')

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('numbered_note',type=Path)
    print(json.dumps(extract(ap.parse_args().numbered_note.read_text()),indent=2))
