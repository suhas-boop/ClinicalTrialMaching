"""Reviewed equivalence of chart measurements. Published cutoffs stay in trial rules."""
import json
from pathlib import Path

FAMILIES = json.loads(Path(__file__).with_name('measurement_families.json').read_text())


def check_family_selectors(family_id, contracts, bindings):
    """All selectors for an admissible reporting form must preserve its declared scope."""
    for key, form in FAMILIES[family_id]['forms'].items():
        selectors = contracts[bindings[key]]['native']
        if not selectors or any(selector != form['selector'] for selector in selectors):
            raise ValueError('Unapproved measurement unit, context or selector for '+key)
