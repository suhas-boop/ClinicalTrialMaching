"""Evaluate a versioned screening agreement and route a missing response to its respondent."""
import calendar
import re
from datetime import date
from zoneinfo import ZoneInfo

from evidence import boolean_answer, codes, decision, instant, ref, references, require, single


def adult_on(dob, day, threshold):
    require(dob <= day, 'Check the patient’s birth date against the screening date.')
    if (dob.month, dob.day) == (2, 29) and (day.month, day.day) == (2, 28):
        require(day.year - dob.year != threshold or calendar.isleap(day.year),
                'Verify the applicable age on this leap-day birthday boundary.')
    age = day.year - dob.year - ((day.month, day.day) < (dob.month, dob.day))
    return age >= threshold


def covers(period, when):
    return bool(period.get('start') and instant(period['start']) <= when
                and (not period.get('end') or when <= instant(period['end'])))


def representative_evidence(chart, actor, when, form):
    logical = actor.split('/_history/')[0]
    person = chart.resources.get(logical)
    require(person and person['resourceType'] == 'RelatedPerson' and ref(person) == actor,
            'Verify the exact RelatedPerson version for the respondent.')
    subjects = {chart.person, ref(chart.patient)}
    visits = {chart.visit, ref(chart.encounter)}
    roles = {label for c in person.get('relationship', []) for label in codes(c, form['role_system'])}
    require(person['patient']['reference'] in subjects and person.get('active') is True
            and form['representative_role'] in roles and covers(person.get('period', {}), when),
            'Verify the respondent’s legal authority for this patient on the date of the agreement.')
    verified = {actor}
    for doc in chart.resources.values():
        if doc['resourceType'] != 'DocumentReference' or doc.get('subject', {}).get('reference') not in subjects:
            continue
        context = doc.get('context', {})
        if not (visits.intersection(references(context.get('encounter', [])))
                and actor in references(context.get('related', []))):
            continue
        if (codes(doc.get('type', {}), form['role_system']) == {form['authority_document_type']}
                and doc.get('status') == 'current' and doc.get('docStatus') in ('final','amended')
                and instant(doc['date']) <= chart.cutoff and covers(context.get('period', {}), when)):
            verified.add(ref(doc))
    require(len(verified) > 1, 'Obtain the documented authority for this representative, trial and screening attempt.')
    return verified


def evaluate_agreement(chart, rule, form, site_zone):
    evidence = set(chart.evidence)
    zone = ZoneInfo(site_zone) if site_zone else chart.cutoff.tzinfo
    subjects = {chart.person, ref(chart.patient)}
    visits = {chart.visit, ref(chart.encounter)}
    threshold = rule['adult_age']
    try:
        birth = chart.patient.get('birthDate', '')
        require(isinstance(birth, str) and re.fullmatch(r'\d{4}-\d\d-\d\d', birth),
                'Obtain the complete birth date to identify the required respondent.')
        dob = date.fromisoformat(birth)
        adult = adult_on(dob, chart.end.astimezone(zone).date(), threshold)
        recipient = 'participant' if adult else 'legal_representative'
        answers = {'participant': set(), 'legal_representative': set()}
        stale_form = False
        unfinished = set()
        for response in chart.resources.values():
            if response['resourceType'] != 'QuestionnaireResponse':
                continue
            if (response.get('subject', {}).get('reference') not in subjects
                    or response.get('encounter', {}).get('reference') not in visits
                    or response.get('status') == 'entered-in-error'):
                continue
            canonical = response.get('questionnaire', '')
            if not isinstance(canonical, str) or canonical.split('|')[0] != form['questionnaire'].split('|')[0]:
                continue
            authored = instant(response['authored'])
            if not chart.start <= authored <= chart.end:
                continue
            if canonical != form['questionnaire']:
                stale_form = True
                continue
            if adult_on(dob, authored.astimezone(zone).date(), threshold) != adult:
                # An earlier answer used a different age-based respondent during this visit.
                continue
            actor = response.get('source', {}).get('reference', '')
            role = 'participant' if actor in subjects else 'legal_representative'
            if role == 'legal_representative':
                require(actor.startswith('RelatedPerson/'), 'Identify the person who actually answered the agreement.')
                if adult:
                    continue
            evidence.add(ref(response))
            if role == 'legal_representative':
                evidence.update(representative_evidence(chart, actor, authored, form))
            if response.get('status') == 'in-progress':
                if role == recipient:
                    unfinished.add(ref(response))
                continue
            require(response.get('status') in ('completed', 'amended'), 'Verify the disposition of the existing agreement response.')
            definition = form['items'][role]
            items = [i for i in response.get('item', []) if i.get('linkId') == definition['link_id']]
            item = single(items, 'Verify the precise agreement item and the person who answered it.')
            require('text' not in item or item['text'] == definition['text'],
                    'Verify that the agreement covers the specified trial types, enrollment period and exception.')
            other_ids = {d['link_id'] for r, d in form['items'].items() if r != role}
            require(not any(i.get('linkId') in other_ids and i.get('answer') for i in response.get('item', [])),
                    'Separate the answers given by different respondents.')
            require(not item.get('modifierExtension') and not any(a.get('modifierExtension') for a in item.get('answer', [])),
                    'Verify the meaning of the modified agreement item.')
            if not item.get('answer'):
                if role == recipient:
                    unfinished.add(ref(response))
                continue
            answers[role].add(boolean_answer(item))

        values = answers[recipient]
        require(len(values) <= 1, 'Reconcile conflicting responses from the required respondent.')
        if values == {False}:
            return decision('NOT_MET', 'The required respondent declined the scoped agreement.', evidence)
        if not adult and False in answers['participant']:
            return decision('INVESTIGATOR_ACTIONS', 'The adolescent expressed an objection. Reconcile the responses with the study team.', evidence)
        if values:
            return decision('MET', 'The required respondent agreed to the trial participation restriction with its survival follow-up exception.', evidence)
        require(not stale_form, 'Verify the questionnaire version and wording before using or repeating the agreement.')
        question = form['items'][recipient]
        result = decision('PATIENT_SURVEY', 'Obtain the agreement from the required respondent.', evidence)
        result['survey'] = {'recipient': recipient, 'questionnaire': form['questionnaire'],
                            'link_id': question['link_id'], 'text': question['text']}
        if unfinished:
            result['survey']['existing_responses'] = sorted(unfinished)
        return result
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        return decision('MISSING_DATA', str(error), evidence)
