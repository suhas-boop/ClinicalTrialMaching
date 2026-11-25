"""Frozen SOTIO I06 examples on synthetic FHIR snapshots. Called by verify.py."""
import json
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

from screen import run

ROOT = Path(__file__).resolve().parent
STUDY = '106S01'
KEY = '106S01-I06'
CUTOFF = '2026-11-19T19:00:00Z'


def fixture():
    return json.loads((ROOT / 'demo-sotio-i06.json').read_text())


def resource(bundle, identifier):
    return next(e['resource'] for e in bundle['entry'] if e['resource']['id'] == identifier)


def remove(bundle, *ids):
    bundle['entry'] = [e for e in bundle['entry'] if e['resource']['id'] not in ids]


def archive(reason='unsafe', form='ffpe-block'):
    b = fixture()
    specimen = resource(b, 'tumor')
    specimen['type']['coding'][0]['code'] = 'archival-tumor-biopsy'
    specimen['collection']['collectedDateTime'] = '2025-12-01T12:00:00Z'
    specimen['container'][0]['type']['coding'][0]['code'] = form
    resource(b, 'archive-review')['valueBoolean'] = True
    resource(b, 'feasibility')['valueCodeableConcept']['coding'][0]['code'] = reason
    return b


def pending():
    b = fixture()
    remove(b, 'central-ihc', 'ihc', 'staining', 'tumor')
    return b


def open_prescreen(b):
    remove(b,'screen','signed-main','doc-signed-main')
    visit=resource(b,'pre')
    visit['period'].pop('end')
    visit.update(status='in-progress')
    visit['meta']['lastUpdated']=visit['period']['start']
    return b


def signing_time(b, id, time):
    event = resource(b, 'signed-' + id)
    doc = resource(b, 'doc-signed-' + id)
    event.update(effectiveDateTime=time, issued=time, valueDateTime=time)
    doc['date'] = time


def prescreen_checks():
    rows = []

    def check(label, b, expected, visit='screen', cutoff=CUTOFF):
        outcome = run(STUDY, b, 'demo', visit, cutoff, timezone_name='UTC')
        actual = outcome['criteria'][KEY]
        assert actual['state'] == expected, (label, actual)
        if expected == 'AUTHORING_HOLD':
            assert KEY in outcome['pipeline_holds'] and actual['question_id'] == 'SOTIO-I06-ARCHIVE'
        else:
            assert KEY in outcome['outputs'][expected]
        if expected in ('MET', 'NOT_MET') and 'qualified_report' in actual:
            evidence = actual['evidence']
            for kind in ('DiagnosticReport/', 'Observation/', 'Specimen/', 'Condition/', 'ServiceRequest/', 'Organization/', 'DocumentReference/', 'EpisodeOfCare/'):
                assert any(r.startswith(kind) and '/_history/' in r for r in evidence), (label, kind)
        rows.append(dict(study=STUDY, criterion='I06', case=label, expected=expected, actual=actual['state']))
        return actual

    check('fresh specimen, exactly 1 percent at intensity 1+ or stronger', fixture(), 'MET')
    for percentage, comparator, want in [(0.99,None,'NOT_MET'), (0,None,'NOT_MET'), (100,None,'MET'),
                                        (1,'<','NOT_MET'), (1,'>=','MET'), (1,'<=','MISSING_DATA'),
                                        (0,'>','MISSING_DATA'), (101,None,'MISSING_DATA')]:
        b = fixture()
        quantity = resource(b, 'staining')['valueQuantity']
        quantity['value'] = percentage
        if comparator:
            quantity['comparator'] = comparator
        check(f'percent {comparator or "="} {percentage}', b, want)

    for reason, form in [('unsafe','ffpe-block'), ('site-inaccessible','unstained-ffpe-slides')]:
        b = archive(reason, form)
        remove(b, 'biopsy-preference')
        check(f'qualified archive {reason} using {form}', b, 'MET')
    check('archive only with fresh biopsy explicitly feasible', archive('safe-and-accessible'), 'AUTHORING_HOLD')
    b = archive()
    remove(b, 'feasibility')
    check('obtain reason for archival route from clinical team', b, 'INVESTIGATOR_ACTIONS')
    check('ineligible archival material cannot establish a negative or positive result', archive(form='stained-slides'), 'MISSING_DATA')

    b = pending()
    remove(b, 'biopsy-preference')
    check('formal screening prompts retrieval of prior records before patient outreach', b, 'MISSING_DATA')
    check('confirmed archive unavailable during prescreen, ask patient about biopsy', open_prescreen(b), 'PATIENT_SURVEY','pre')
    b = pending()
    check('willing patient awaits assay', b, 'MISSING_DATA')
    resource(b,'biopsy-preference')['item'][0]['answer'][0]['valueBoolean'] = False
    check('explicitly no adequate archive and fresh biopsy declined', b, 'NOT_MET')
    remove(b, 'archive-review')
    check('refusal with unknown archive availability', b, 'MISSING_DATA')
    b = pending()
    resource(b,'archive-review')['focus'][0]['reference']='Condition/other/_history/1'
    resource(b,'biopsy-preference')['item'][0]['answer'][0]['valueBoolean']=False
    check('another tumor’s tissue review cannot close a route', b, 'MISSING_DATA')
    b = pending()
    resource(b,'archive-review')['valueBoolean'] = True
    remove(b,'biopsy-preference')
    check('available archive avoids unnecessary survey', b, 'MISSING_DATA')
    b = pending()
    resource(b,'biopsy-preference')['source']['reference'] = 'Patient/other'
    check('unverified survey respondent cannot decline for this patient', b, 'MISSING_DATA')

    b = pending()
    remove(b,'biopsy-preference')
    resource(b,'feasibility')['valueCodeableConcept']['coding'][0]['code'] = 'unsafe'
    check('avoid asking the patient for an unsafe fresh procedure', b, 'INVESTIGATOR_ACTIONS')
    b = fixture()
    remove(b,'ihc','staining','biopsy-preference')
    check('existing trial order avoids a duplicate survey', b, 'MISSING_DATA')
    b = archive()
    resource(b,'feasibility').update(effectiveDateTime='2026-11-14T09:00:00Z',issued='2026-11-14T10:00:00Z')
    check('new clinical judgment cannot justify an earlier sample selection', b, 'INVESTIGATOR_ACTIONS')

    for label, modify in [
        ('fresh submission form requires verification',lambda b: resource(b,'tumor').pop('container')),
        ('needle aspirate is insufficient',lambda b: resource(b,'tumor')['collection']['method']['coding'][0].update(code='fine-needle-aspirate')),
        ('unverified tissue adequacy', lambda b: resource(b,'tumor').pop('condition')),
        ('report from a local lab', lambda b: resource(b,'central')['identifier'][0].update(value='site-lab')),
        ('result release after screening began', lambda b: resource(b,'ihc').update(issued='2026-11-19T10:00:00Z')),
        ('report released after frozen cutoff', lambda b: resource(b,'ihc').update(issued='2026-11-20T12:00:00Z')),
        ('wrong patient on specimen', lambda b: resource(b,'tumor')['subject'].update(reference='Patient/other')),
        ('other indexed tumor on order', lambda b: resource(b,'central-ihc')['reasonReference'][0].update(reference='Condition/other/_history/1')),
        ('specimen version differs',lambda b: resource(b,'staining')['specimen'].update(reference='Specimen/tumor/_history/2')),
        ('unqualified percent without intensity denominator',lambda b: resource(b,'staining')['code']['coding'][0].update(code='generic-percent-positive')),
        ('wrong assay method',lambda b: resource(b,'staining')['method']['coding'][0].update(code='sequencing')),
        ('wrong units',lambda b: resource(b,'staining')['valueQuantity'].update(code='1')),
        ('foreign prescreen attempt',lambda b: resource(b,'pre')['episodeOfCare'][0].update(reference='EpisodeOfCare/other/_history/1')),
        ('future consent form version',lambda b: resource(b,'doc-signed-main')['meta'].update(lastUpdated='2026-11-20T12:00:00Z')),
        ('assay before tissue collected',lambda b: resource(b,'tumor')['collection'].update(collectedDateTime='2026-11-13T09:00:00Z')),
        ('screening requires an actual main ICF',lambda b: remove(b,'signed-main')),
        ('actual prescreen consent missing',lambda b: remove(b,'signed-pre')),
    ]:
        b = fixture()
        modify(b)
        check(label, b, 'MISSING_DATA')

    for days,want in [(90,'MET'), (91,'MISSING_DATA')]:
        b=fixture()
        when=(datetime.fromisoformat('2026-11-18T09:00:00+00:00')-timedelta(days=days)).isoformat()
        signing_time(b,'pre',when)
        resource(b,'pre')['period']['start']=when
        check(f'consent dates {days} calendar days apart', b, want)

    b=fixture()
    second=deepcopy(resource(b,'ihc'));second['id']='other-report'
    b['entry'].append({'resource':second})
    check('ambiguous governing central report',b,'MISSING_DATA')
    b=open_prescreen(fixture())
    cutoff='2026-11-13T00:00:00Z'
    check('positive central result during open prescreen',b,'MET','pre',cutoff)
    other=run(STUDY,b,'demo','pre',cutoff)['criteria'][STUDY+'-I04']['state']
    assert other=='MISSING_DATA', 'Prescreen encounter must not trigger formal screening evaluations.'
    b=pending()
    first=check('incremental initial result is pending',b,'MISSING_DATA')
    later=fixture()
    final=check('incremental result and specimen arrive',later,'MET')
    duplicate=run(STUDY,deepcopy(later),'demo','screen',CUTOFF,timezone_name='UTC')['criteria'][KEY]
    assert first['state'] != final['state'] and final==duplicate
    from onboarding import packet_answers, validate
    saved = json.loads((ROOT / 'demo-sotio-onboarding.json').read_text())
    legacy = deepcopy(saved)
    legacy['questions'] = [q for q in legacy['questions'] if q['id'] != 'SOTIO-I06-ARCHIVE']
    legacy['questions'][0].update(answer='Synthetic prior answer', authority='Demo coordinator', decision_date='2026-11-19')
    enriched = validate(legacy,STUDY)
    assert enriched['questions'][:-1] == legacy['questions']
    added = enriched['questions'][-1]
    assert added['id']=='SOTIO-I06-ARCHIVE' and added['answer'] is None
    assert packet_answers(enriched,KEY) == []
    added.update(answer='Synthetic workflow test only.', authority='Demo coordinator', decision_date='2026-11-19')
    answer=packet_answers(validate(enriched,STUDY), KEY)
    assert len(answer)==1 and answer[0]['question_id']==added['id'] and answer[0]['protocol_sha256']==saved['protocol_sha256']
    rows.append(dict(study=STUDY, criterion='I06', case='prior onboarding preserves answers and adds a scoped unanswered question',
                     expected='PASS', actual='PASS'))
    return rows
