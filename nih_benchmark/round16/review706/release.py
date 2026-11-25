"""Activate one verified interpretation in the normal catalog and FHIR screening path."""
from copy import deepcopy
from .clarify import CASE, DIGEST, STUDY, CurrentComplaints, reviewed_rule, verify_answer
from catalog import contract, FACTS, verify
from match import screen
from run import fingerprint

READER = 'reviewed-current-complaints-r1'
BASE_ENTRY_SHA256 = '9bb1dfb20bbd0c294097f5b646355aa8b8c6be9f6908021f44a59ca46c6ca989'


def screen_reviewed(resources, subject, pack, study, criterion=None, *, envelope, trust, protocol_bytes, as_of):
    if envelope is None:
        return screen(resources, subject, pack, study, criterion)
    if study != STUDY or criterion not in (CASE, None):
        raise ValueError('Provided review covers a different trial or criterion')
    verify(pack)
    old = pack['rules'][CASE]
    if fingerprint(old) != BASE_ENTRY_SHA256:
        raise ValueError('The original reviewed question or source has changed')
    approved = verify_answer(envelope, trust, protocol_bytes, as_of)
    rule = reviewed_rule(approved['interpretation'])
    decision = {k:approved[k] for k in ('decision_id','decision_date','authority_id',
                'governing_version','governing_protocol_sha256','source_locator')}
    decision.update(signed_answer_sha256=fingerprint(envelope),rule_sha256=fingerprint(rule),registry_sha256=DIGEST)
    return _screen_interpretation(resources, subject, pack, study, criterion, rule, 'protocol_decision', decision)


def _screen_interpretation(resources, subject, pack, study, criterion, rule, source_field, decision):
    """Bind a caller-validated interpretation to the same FHIR readers, with its explicit provenance."""
    overlay = deepcopy(pack)
    entry = overlay['rules'][CASE]
    entry['source'][source_field] = decision
    entry['rule'] = rule
    entry['bindings'] = {}
    for name,spec in rule['facts'].items():
        cid = contract(spec)
        selectors = [dict(resource='DocumentReference',local_code=name,context='current patient presentation',read=READER)]
        definition = dict(spec=spec, normalized_system=FACTS, native=selectors)
        if overlay['contracts'].setdefault(cid, definition) != definition:
            raise ValueError('New rule conflicts with an existing evidence contract')
        entry['bindings'][name] = cid
    overlay['sha256'] = fingerprint({k:v for k,v in overlay.items() if k!='sha256'})
    verify(overlay)
    readers = {}
    if subject.startswith('Patient/'):
        bundle = dict(resourceType='Bundle', entry=[{'resource':r} for r in resources])
        readers[READER] = CurrentComplaints(bundle, subject.split('/',1)[1])
    result = screen(resources,subject,overlay,study,criterion,document_readers=readers)
    result[source_field] = decision
    result['base_catalog_sha256'] = pack['sha256']
    row = result['criteria'][CASE]
    row['rule'] = rule
    spans = readers[READER].spans if readers else {}
    row['source_spans'] = {ref:span for ref,span in spans.items() if ref in row['evidence']}
    return result
