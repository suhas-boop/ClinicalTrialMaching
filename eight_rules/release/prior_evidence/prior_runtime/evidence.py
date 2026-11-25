"""Shared helpers for the normalized FHIR snapshot and its decisions."""
import re
from datetime import datetime

def instant(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})',value):
        raise ValueError('A timezone-qualified timestamp is required.')
    return datetime.fromisoformat(value.replace('Z','+00:00'))

def ref(resource):
    return resource['resourceType']+'/'+resource['id']+'/_history/'+resource['meta']['versionId']

def single(items,reason):
    if len(items)!=1: raise ValueError(reason)
    return items[0]

def decision(state,reason,evidence=()):
    return {'state':state,'reason':reason,'evidence':sorted(set(evidence))}


def meets_inclusive_minimum(comparator, value, minimum):
    """Determine whether every value allowed by a numeric bound meets the minimum."""
    if comparator in (None, '=', '>', '>=') and value >= minimum:
        return True
    if comparator in (None, '=', '<', '<=') and value < minimum:
        return False
    if comparator == '<' and value == minimum:
        return False
    return None


def codes(concept, system):
    return {c['code'] for c in concept.get('coding', []) if c.get('system') == system}


def references(items):
    return [item.get('reference') for item in items]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def only_value(resource, field):
    require({k for k in resource if k.startswith('value')} == {field}
            and 'dataAbsentReason' not in resource, 'Verify the documented ' + field + '.')
    return resource[field]


def boolean_answer(item):
    answer = single(item.get('answer', []), 'Verify the recorded response to the agreement.')
    value = only_value(answer, 'valueBoolean')
    require(type(value) is bool, 'Verify the recorded yes/no response.')
    return value
