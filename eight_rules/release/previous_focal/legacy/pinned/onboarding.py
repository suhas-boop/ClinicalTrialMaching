"""Create one coordinator intake per uploaded protocol version and reuse it on later runs."""
import argparse
import hashlib
import json
import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from zipfile import ZipFile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

HERE = Path(__file__).resolve().parent
STUDIES = json.loads((HERE / 'inventory.json').read_text())['studies']
QUESTIONS = json.loads((HERE / 'coordinator_questions.json').read_text())
SCHEMA = 'pocketmd-trial-onboarding-v1'


def timestamp(value):
    if not isinstance(value, str) or 'T' not in value:
        raise ValueError('The upload timestamp must include time and UTC offset.')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('The upload timestamp must include a UTC offset.')
    return parsed


def create_profile(study, archive, timezone, uploaded_at=None, simulate=False):
    spec = STUDIES[study]
    with ZipFile(archive) as source:
        digest = hashlib.sha256(source.read(spec['protocol_member'])).hexdigest()
    if digest != spec['protocol_sha256']:
        raise ValueError('The uploaded protocol differs from the indexed version.')
    zone = ZoneInfo(timezone)
    uploaded = timestamp(uploaded_at) if uploaded_at else datetime.now(zone)
    return {'schema': SCHEMA, 'study': study, 'protocol_sha256': digest,
            'version': spec['version'], 'timezone': timezone,
            'uploaded_at': uploaded.astimezone(zone).isoformat(),
            'test_cycle_start_offset_days': 7 if simulate else None,
            'questions': [{**q, 'answer': None, 'authority': None, 'decision_date': None}
                          for q in QUESTIONS.get(study, [])]}


def validate(profile, study):
    if (profile.get('schema') != SCHEMA or profile.get('study') != study
            or profile.get('protocol_sha256') != STUDIES[study]['protocol_sha256']):
        raise ValueError('Onboarding record is for a different study or amendment.')
    ZoneInfo(profile['timezone'])
    timestamp(profile['uploaded_at'])
    offset = profile['test_cycle_start_offset_days']
    if offset is not None and (type(offset) is not int or offset != 7):
        raise ValueError('Unsupported test cycle-start assumption.')
    expected = {q['id']: q for q in QUESTIONS.get(study, [])}
    seen = set()
    for q in profile['questions']:
        template = expected.get(q['id'])
        if template is None or q['id'] in seen or any(q.get(k) != v for k, v in template.items()):
            raise ValueError('Question does not match the uploaded protocol questionnaire.')
        seen.add(q['id'])
        fields = [q.get(k) for k in ('answer','authority','decision_date')]
        if any(v is not None for v in fields):
            if not all(isinstance(v,str) and v.strip() for v in fields):
                raise ValueError('Record an answer, authority, and decision date together.')
            date.fromisoformat(q['decision_date'])
        for field in ('interpretation','source_reference'):
            if q.get(field) is not None and (not q.get('answer') or not isinstance(q[field],str) or not q[field].strip()):
                raise ValueError('Supply a recorded answer and a nonempty ' + field + '.')
    unlisted = [q for q in expected.values() if q['id'] not in seen]
    if any('when' not in q for q in unlisted):
        raise ValueError('An onboarding question is missing.')
    if unlisted:
        # Earlier profiles predate these conditional cases. Keep recorded answers intact.
        additions = [dict(q, answer=None, authority=None, decision_date=None) for q in unlisted]
        return {**profile, 'questions': [*profile['questions'], *additions]}
    return profile


def test_cycle(profile, cutoff=None):
    offset = profile['test_cycle_start_offset_days']
    if offset is None:
        return None
    uploaded = timestamp(profile['uploaded_at'])
    if cutoff is not None and timestamp(cutoff) < uploaded:
        raise ValueError('The simulated trial configuration was unavailable at the replay cutoff.')
    onboard_day = uploaded.astimezone(ZoneInfo(profile['timezone'])).date()
    return {'basis': 'simulation_only', 'onboarded_on': onboard_day.isoformat(),
            'offset_calendar_days': offset, 'cycle_1_day_1': (onboard_day + timedelta(days=offset)).isoformat(),
            'timezone': profile['timezone']}


def packet_answers(profile, criterion):
    return [{'criterion': criterion, 'protocol_sha256': profile['protocol_sha256'],
             'question': q['question'], 'answer': q['answer'], 'authority': q['authority'],
             'decision_date': q['decision_date'], 'question_id': q['id'],
             **{k:q[k] for k in ('interpretation','source_reference') if q.get(k)}}
            for q in profile['questions'] if q['criterion']==criterion and q.get('answer')]


def install(path, proposed):
    # An atomic create makes upload retries and concurrent uploads reuse the original clock.
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as output:
        temp = Path(output.name)
        json.dump(proposed,output,indent=2);output.write('\n')
    try:
        try:
            os.link(temp,path)
        except FileExistsError:
            existing=validate(json.loads(path.read_text()),proposed['study'])
            for k in ('timezone','test_cycle_start_offset_days'):
                if existing[k]!=proposed[k]:
                    raise ValueError('Existing onboarding configuration differs. Use its original settings or choose a separate test profile.')
            return existing
        return proposed
    finally:
        temp.unlink(missing_ok=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('study',choices=STUDIES);p.add_argument('site_zip',type=Path);p.add_argument('profile',type=Path)
    p.add_argument('--timezone',default='UTC',help='Trial onboarding time zone, e.g. America/Los_Angeles. Defaults to UTC.')
    p.add_argument('--uploaded-at',help='Recorded upload timestamp for importing an earlier upload. Defaults to now.')
    p.add_argument('--test-cycle-start',action='store_true',help='In this test profile only, model C1D1 seven calendar days after onboarding.')
    a=p.parse_args()
    try:
        result=install(a.profile,create_profile(a.study,a.site_zip,a.timezone,a.uploaded_at,a.test_cycle_start))
        print(json.dumps({'profile':str(a.profile),'uploaded_at':result['uploaded_at'],'simulated_schedule':test_cycle(result),
                          'coordinator_questions':[q for q in result['questions'] if q['answer'] is None]},indent=2))
    except (ValueError, KeyError, OSError, ZoneInfoNotFoundError) as error:
        p.error(str(error))
