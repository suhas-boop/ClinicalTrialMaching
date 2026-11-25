"""Identify the sentence added by NIH's public TrialGPT matching script in its own corpus."""
import base64
from functools import cache
from hashlib import sha256
import json
from pathlib import Path

APPENDED = 'The patient will provide informed consent, and will comply with the trial protocol without any practical issues.'
PRODUCER = 'https://github.com/ncbi-nlp/TrialGPT/blob/97ba047695ca77bfe8d3634c10cbe10b0095929f/trialgpt_matching/run_matching.py#L33'
ROLE = 'urn:pocketmd:document-source-role'
MANIFEST = Path(__file__).resolve().parents[1]/'round9/note_hashes.json'
MANIFEST_SHA256 = '0c58534dd5b04ec98670b85b5d028e17fac2cfe9250b4d3c4aa781e8ac4cbdec'


@cache
def note_hashes():
    data = MANIFEST.read_bytes()
    if sha256(data).hexdigest() != MANIFEST_SHA256:
        raise ValueError('TrialGPT source manifest changed')
    return json.loads(data)


def apply_benchmark_origin(pid, raw, bundle, spans):
    """Mark a frozen augmented note, preserving its bytes and every clinical source offset."""
    digest = sha256(raw.encode()).hexdigest()
    if note_hashes().get(pid) != digest:
        raise ValueError('Input differs from the pinned TrialGPT note for this subject')
    lines = raw.splitlines()
    n = len(lines) - 1
    if n < 1 or lines[n] != f'{n}. {APPENDED}':
        raise ValueError('TrialGPT suffix has changed')
    docs = [e['resource'] for e in bundle['entry'] if e['resource']['resourceType'] == 'DocumentReference']
    if len(docs) != 1:
        raise ValueError('Expected one frozen TrialGPT source document')
    doc = docs[0]
    if (doc['id'] != pid+'-note' or doc['subject']['reference'] not in {'Patient/'+pid,'Group/'+pid}
            or base64.b64decode(doc['content'][0]['attachment']['data'],validate=True) != raw.encode()
            or {'system':'urn:pocketmd:sha256','value':digest} not in doc['identifier']):
        raise ValueError('TrialGPT source identity or attachment differs')
    start = raw.rindex(APPENDED)
    doc.setdefault('extension',[]).append({
        'url':ROLE, 'extension':[
            {'url':'role','valueCode':'benchmark-assumption'},
            {'url':'producer','valueUrl':PRODUCER},
            {'url':'sourceSentence','valueInteger':n},
            {'url':'characterStart','valueInteger':start},
            {'url':'characterEnd','valueInteger':start+len(APPENDED)},
        ]})
    # Covers both the initial structured converter and the prose enrichment pass.
    # A multi-sentence assertion drawing on the supplement is also unsuitable.
    excluded = {s['resource'] for s in spans if n in s['sentences']}
    def keep(entry):
        r = entry['resource']
        if r['resourceType'] == 'Provenance':
            return not any(t.get('reference') in excluded for t in r['target'])
        return r['resourceType']+'/'+r['id'] not in excluded
    bundle['entry'] = [e for e in bundle['entry'] if keep(e)]
    return bundle,[s for s in spans if s['resource'] not in excluded]
