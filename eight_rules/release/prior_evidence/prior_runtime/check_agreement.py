"""Synthetic SOTIO I07 responder, authority, scope and replay examples."""
import json
from copy import deepcopy
from pathlib import Path

from screen import CATALOG_DATA, run

ROOT = Path(__file__).resolve().parent
KEY = '106S01-I07'
CUTOFF = '2026-11-19T12:00:00Z'
FORM = CATALOG_DATA['agreement_forms']['other-interventional-agreement']


def sample():
    return json.loads((ROOT / 'demo-sotio-i07.json').read_text())


def resource(bundle, identifier):
    return next(row['resource'] for row in bundle['entry'] if row['resource']['id'] == identifier)


def remove(bundle, *ids):
    bundle['entry'] = [row for row in bundle['entry'] if row['resource']['id'] not in ids]


def set_answer(response, role, value):
    item = FORM['items'][role]
    response['source'] = {'reference': 'Patient/demo' if role == 'participant' else 'RelatedPerson/guardian/_history/1'}
    response['item'] = [{'linkId': item['link_id'], 'text': item['text'], 'answer': [{'valueBoolean': value}]}]


def adult(value=True, birth='1990-11-19'):
    bundle = sample()
    resource(bundle,'demo')['birthDate'] = birth
    set_answer(resource(bundle,'agreement'),'participant',value)
    return bundle


def extra_answer(bundle, role, value):
    other = deepcopy(resource(bundle,'agreement'))
    other['id']='other-answer'
    set_answer(other,role,value)
    bundle['entry'].append({'resource':other})


def agreement_checks():
    cases = []
    def check(label,b,expected,recipient=None,cutoff=CUTOFF,zone='UTC'):
        run_result = run('106S01',b,'demo','screen',cutoff,timezone_name=zone)
        result = run_result['criteria'][KEY]
        assert result['state']==expected and KEY in run_result['outputs'][expected], (label,result)
        if recipient:
            assert result['survey']['recipient']==recipient and result['survey']['text']==FORM['items'][recipient]['text'], (label,result)
        if expected in ('MET','NOT_MET'):
            assert any(link.startswith('QuestionnaireResponse/') and '/_history/' in link for link in result['evidence'])
        cases.append(dict(study='106S01',criterion='I07',case=label,expected=expected,actual=result['state']))
        return result

    for item in FORM['items'].values():
        assert 'other interventional clinical trials' in item['text'] and 'while enrolled in SOTIO 106S01' in item['text']
        assert 'except during the survival follow-up period' in item['text']
    check('adult explicitly agrees',adult(),'MET')
    check('adult explicitly declines',adult(False),'NOT_MET')
    check('18th birthday routes to participant',adult(birth='2008-11-19'),'MET')
    b=adult(birth='2008-11-20')
    check('day before 18th birthday requires representative',b,'PATIENT_SURVEY','legal_representative')
    b=adult();remove(b,'agreement')
    check('missing adult response requests precisely scoped patient survey',b,'PATIENT_SURVEY','participant')
    b=sample();remove(b,'agreement')
    check('missing response for minor routes survey to legal representative',b,'PATIENT_SURVEY','legal_representative')
    b=sample()
    r=check('representative agrees for minor with verified authority',b,'MET')
    assert {'RelatedPerson/guardian/_history/1','DocumentReference/authority/_history/1'}.issubset(r['evidence'])
    set_answer(resource(b,'agreement'),'legal_representative',False)
    check('verified representative declines',b,'NOT_MET')
    b=sample();extra_answer(b,'participant',False)
    check('recorded adolescent objection with representative agreement',b,'INVESTIGATOR_ACTIONS')
    b=sample();set_answer(resource(b,'agreement'),'participant',True)
    check('adolescent agreement alone',b,'PATIENT_SURVEY','legal_representative')
    b=sample();resource(b,'demo')['birthDate']='1980-01-01'
    check('representative response alone for adult',b,'PATIENT_SURVEY','participant')
    b=sample();set_answer(resource(b,'agreement'),'legal_representative',False);extra_answer(b,'participant',True)
    check('participant agreement cannot cancel representative refusal',b,'NOT_MET')

    for label,modify in [
        ('family relationship alone',lambda b:resource(b,'guardian')['relationship'][0]['coding'][0].update(code='parent')),
        ('authority document absent',lambda b:remove(b,'authority')),
        ('authority document for another patient',lambda b:resource(b,'authority')['subject'].update(reference='Patient/other')),
        ('authority document for another visit',lambda b:resource(b,'authority')['context']['encounter'][0].update(reference='Encounter/other')),
        ('authority document for another representative version',lambda b:resource(b,'authority')['context']['related'][0].update(reference='RelatedPerson/guardian/_history/2')),
        ('representative authority expired',lambda b:resource(b,'guardian')['period'].update(end='2026-11-18T23:59:59Z')),
        ('document authority begins after response',lambda b:resource(b,'authority')['context']['period'].update(start='2026-11-19T09:45:00Z')),
        ('unavailable authority document at cutoff',lambda b:resource(b,'authority')['meta'].update(lastUpdated='2026-11-20T00:00:00Z')),
        ('wrong representative patient',lambda b:resource(b,'guardian')['patient'].update(reference='Patient/other')),
        ('unversioned representative',lambda b:resource(b,'agreement')['source'].update(reference='RelatedPerson/guardian')),
        ('recording author does not establish respondent',lambda b:(resource(b,'agreement').update(author={'reference':'RelatedPerson/guardian/_history/1'}),resource(b,'agreement').pop('source'))),
        ('incomplete date of birth',lambda b:resource(b,'demo').update(birthDate='2009')),
        ('future date of birth',lambda b:resource(b,'demo').update(birthDate='2027-01-01')),
        ('wrong amendment of same questionnaire',lambda b:resource(b,'agreement').update(questionnaire=FORM['questionnaire'].split('|')[0]+'|retired')),
        ('broader wording omits survival exception',lambda b:resource(b,'agreement')['item'][0].update(text='Will the participant avoid every study throughout all follow-up?')),
        ('unknown or obsolete question',lambda b:resource(b,'agreement')['item'][0].update(linkId='unspecified-restriction')),
        ('clinician recorded as person answering',lambda b:resource(b,'agreement')['source'].update(reference='Practitioner/demo')),
        ('text acknowledgement is not a bound boolean',lambda b:resource(b,'agreement')['item'][0].update(answer=[{'valueString':'Yeah'}])),
        ('contradictory values in one answer',lambda b:resource(b,'agreement')['item'][0]['answer'][0].update(valueString='no')),
    ]:
        b=sample();modify(b);check(label,b,'MISSING_DATA')

    b=adult();o=resource(b,'agreement');o['author']={'reference':'Practitioner/recorder'}
    check('staff may record the patient’s own answer',b,'MET')
    b=adult();extra_answer(b,'participant',False)
    check('conflicting completed participant answers',b,'MISSING_DATA')
    b=sample();extra_answer(b,'legal_representative',True)
    check('concordant records give the same result',b,'MET')
    b=adult()
    extra_answer(b,'participant',False);resource(b,'other-answer')['status']='entered-in-error'
    check('entered-in-error answer cannot create a refusal',b,'MET')
    b=adult();r=resource(b,'agreement');r['subject']={'reference':'Patient/other'}
    check('another patient’s response cannot resolve the item',b,'PATIENT_SURVEY','participant')
    b=adult();resource(b,'agreement')['encounter']={'reference':'Encounter/prior'}
    check('previous screening attempt cannot resolve current agreement',b,'PATIENT_SURVEY','participant')
    b=adult();resource(b,'agreement').update(questionnaire='https://example.org/Questionnaire/general-consent|1')
    check('general consent alone cannot resolve the agreement',b,'PATIENT_SURVEY','participant')
    b=adult();resource(b,'agreement').update(authored='2026-11-19T13:00:00Z')
    check('future answer is unavailable',b,'PATIENT_SURVEY','participant')
    b=adult();resource(b,'agreement')['meta']['lastUpdated']='2026-11-19T12:30:00Z'
    check('new response not yet available at cutoff',b,'PATIENT_SURVEY','participant')
    later=check('same encounter after response arrives',b,'MET',cutoff='2026-11-19T13:00:00Z')
    assert run('106S01',deepcopy(b),'demo','screen','2026-11-19T13:00:00Z',timezone_name='UTC')['criteria'][KEY]==later

    b=adult();resource(b,'agreement')['status']='in-progress'
    pending=check('resume the existing adult survey before scoring',b,'PATIENT_SURVEY','participant')
    assert pending['survey']['existing_responses']==['QuestionnaireResponse/agreement/_history/1']
    b=sample();resource(b,'agreement')['item'][0]['answer']=[]
    check('unanswered item remains a representative survey',b,'PATIENT_SURVEY','legal_representative')
    b=sample();response=resource(b,'agreement')
    response['item'].append({'linkId':FORM['items']['participant']['link_id'],'answer':[{'valueBoolean':False}]})
    check('a single response cannot speak for two decision makers',b,'MISSING_DATA')
    b=adult();resource(b,'agreement')['item'][0]['modifierExtension']=[{'url':'https://example.org/qualification','valueBoolean':True}]
    check('qualified or modified responses require verification',b,'MISSING_DATA')
    b=adult(birth='2008-11-19')
    for item in b['entry']:
        item['resource']['meta']['lastUpdated']='2026-11-18T23:30:00Z'
    resource(b,'screen')['period']['start']='2026-11-18T23:00:00Z'
    resource(b,'agreement')['authored']='2026-11-18T23:20:00Z'
    check('midnight UTC still precedes birthday at site',b,'PATIENT_SURVEY','legal_representative','2026-11-19T00:20:00Z','America/Los_Angeles')

    for course in ('observational','survival-follow-up'):
        b=adult()
        b['entry'].append({'resource':{'resourceType':'ResearchSubject','id':course,'meta':{'versionId':'1','lastUpdated':CUTOFF},
            'status':'on-study','study':{'reference':'ResearchStudy/'+course},'individual':{'reference':'Patient/demo'}}})
        check(course+' record with explicit scoped agreement',b,'MET')
        remove(b,'agreement')
        check(course+' record alone cannot establish agreement',b,'PATIENT_SURVEY','participant')
    return cases


def review_handoff_checks():
    from check_prescreen import archive, CUTOFF as prescreen_cutoff
    from onboarding import packet_answers, validate
    from packet import clarification_handoff
    from screen import INVENTORY, RULES
    criterion='106S01-I06'
    profile=json.loads((ROOT / 'demo-sotio-onboarding.json').read_text())
    q=next(q for q in profile['questions'] if q['id']=='SOTIO-I06-ARCHIVE')
    source=INVENTORY['studies']['106S01']
    comparison=RULES[criterion]['review_comparisons'][q['id']]
    rows=[]
    def check(label, responses, want):
        item=clarification_handoff(criterion,source,q,comparison,responses)
        assert item['status']==want,(label,item['status'])
        rows.append(dict(study='106S01',criterion='I06-authoring',case=label,expected=want,actual=item['status']))
        return item
    original=check('scope question is open by default',packet_answers(validate(profile,'106S01'),criterion),'AWAITING_PROTOCOL_ANSWER')

    for case in original['comparison']['cases']:
        b=archive(case['documented_reason'])
        out=run('106S01',b,'demo','screen',prescreen_cutoff,timezone_name='UTC')['criteria'][criterion]
        want=case['current_expected']
        assert out['state']==want,(case,out)
        rows.append(dict(study='106S01',criterion='I06-authoring',case='paired archival case: '+case['documented_reason'],expected=want,actual=out['state']))

    test_profile=deepcopy(profile)
    sample_q=next(i for i in test_profile['questions'] if i['id']==q['id'])
    sample_q.update(answer='Yes',authority='Synthetic reviewer',decision_date='2026-11-19')
    def responses():
        return packet_answers(validate(test_profile,'106S01'),criterion)
    check('unqualified yes cannot select an interpretation', responses(), 'CLARIFY_INTERPRETATION_OR_SOURCE')
    sample_q.update(answer='Synthetic permissive interpretation.',interpretation='archival_sufficient',
                    source_reference='Synthetic reviewer memo for parser testing only')
    first=check('attributed choice and source go to rule validation',responses(),'ANSWER_RECORDED_FOR_RULE_VALIDATION')
    assert first['context_sha256']!=original['context_sha256']
    assert clarification_handoff(criterion,source,q,comparison,responses())['context_sha256']==first['context_sha256']
    repeated=check('duplicate receipt preserves the context version',responses()+responses(),'ANSWER_RECORDED_FOR_RULE_VALIDATION')
    assert repeated['context_sha256']==first['context_sha256']
    wrong=deepcopy(responses()[0]);wrong['protocol_sha256']='another-amendment'
    check('prior-amendment answer cannot resolve this question',[wrong],'AWAITING_PROTOCOL_ANSWER')
    second=deepcopy(responses()[0])
    second.update(interpretation='infeasibility_required',answer='Synthetic restrictive interpretation.')
    check('conflicting choices require reconciliation',[*responses(),second],'RECONCILE_RESPONSES')
    sample_q.update(interpretation='conditional',answer='Synthetic condition requiring source review.')
    check('qualified answer routes to the rule author',responses(),'CLARIFY_INTERPRETATION_OR_SOURCE')
    assert run('106S01',archive('safe-and-accessible'),'demo','screen',prescreen_cutoff,onboarding=test_profile)['criteria'][criterion]['state']=='AUTHORING_HOLD'
    return rows
