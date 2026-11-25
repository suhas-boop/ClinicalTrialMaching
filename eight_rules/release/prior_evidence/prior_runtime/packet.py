"""Make a source-locked authoring input. Never treat an extraction alone as the approved protocol."""
import argparse,hashlib,json,zipfile
from datetime import date
from pathlib import Path
from screen import INVENTORY,RULES
from onboarding import QUESTIONS,validate,packet_answers
def clarification_handoff(criterion, source, question, comparison, responses):
    """Package an open scope decision and its paired clinical examples for the rule author."""
    linked = []
    for r in responses:
        if (r.get('criterion') == criterion and r.get('protocol_sha256') == source['protocol_sha256']
                and r.get('question_id', question['id']) == question['id'] and r.get('question') == question['question']):
            normalized = {**r, 'question_id':question['id']}
            if normalized not in linked:
                linked.append(normalized)
    linked.sort(key=lambda r: json.dumps(r, sort_keys=True))
    status = 'AWAITING_PROTOCOL_ANSWER'
    if linked:
        choices = {r.get('interpretation') for r in linked}
        if len(choices - {None}) > 1:
            status = 'RECONCILE_RESPONSES'
        elif (None in choices or choices == {'conditional'} or not choices.issubset(comparison['choices'])
              or any(not isinstance(r.get('source_reference'), str) or not r['source_reference'].strip() for r in linked)):
            status = 'CLARIFY_INTERPRETATION_OR_SOURCE'
        else:
            status = 'ANSWER_RECORDED_FOR_RULE_VALIDATION'
    context = {'criterion': criterion, 'protocol_sha256': source['protocol_sha256'],
               'question_id': question['id'], 'question': question['question'],
               'when': question.get('when'), 'protocol_location': question['location'],
               'comparison': comparison, 'responses': linked}
    payload = json.dumps(context, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    return {**context, 'status': status, 'context_sha256': hashlib.sha256(payload).hexdigest()}


def packet(criterion,archive,context_pages,review,onboarding=None):
    row=next(r for r in INVENTORY['criteria'] if r['id']==criterion)
    src=INVENTORY['studies'][row['study']]
    with zipfile.ZipFile(archive) as z:raw=z.read(src['protocol_member'])
    if hashlib.sha256(raw).hexdigest()!=src['protocol_sha256']:raise ValueError('Protocol version differs. Re-inventory this amendment.')
    out={'criterion':row,'source':src,'candidate_rule':RULES.get(criterion),'review_context':[], 'proposed_bindings_are_unverified':True}
    if onboarding is not None:
        profile=validate(json.loads(onboarding.read_text()),row['study'])
        out['review_context'].extend(packet_answers(profile,criterion))
    if review:
        v=json.loads(review.read_text())
        for k in ('criterion','protocol_sha256','question','answer','authority','decision_date'):
            if not isinstance(v.get(k),str) or not v[k].strip():raise ValueError('Missing reviewer decision field '+k)
        if v['criterion']!=criterion or v['protocol_sha256']!=src['protocol_sha256']:raise ValueError('Decision is for another criterion or amendment.')
        date.fromisoformat(v['decision_date'])
        for key in ('interpretation','source_reference'):
            if key in v and (not isinstance(v[key],str) or not v[key].strip()):
                raise ValueError('Supply a nonempty ' + key + ' for the reviewed decision.')
        if 'question_id' in v:
            known = {q['id']:q['question'] for q in QUESTIONS.get(row['study'], []) if q['criterion']==criterion}
            if known.get(v['question_id']) != v['question']:
                raise ValueError('Reviewer decision does not match the scoped question.')
        out['review_context'].append(v)
    out['coordinator_questions']=[question for question in QUESTIONS.get(row['study'], [])
                                  if question['criterion']==criterion]
    comparisons = (out['candidate_rule'] or {}).get('review_comparisons', {})
    out['clarifications'] = [clarification_handoff(criterion, src, q, comparisons[q['id']], out['review_context'])
                             for q in out['coordinator_questions'] if q['id'] in comparisons]
    if src['protocol_member'].endswith('.pdf'):
        reviewed_context={'NEOK001-1-E15': [28, 70], 'NEOK001-1-I06': [70], 'REC-1245-101-E07': [74], 'REC-1245-101-I05': [102], '106S01-I15': [63]}
        pages=sorted(set(range(row['pdf_pages'][0],row['pdf_pages'][1]+1))|set(context_pages)|set(row.get('context_pages',[]))|set(reviewed_context.get(criterion,[])))
        out['source_pages']=pages
        out['instruction']='Inspect the attached original page images, follow governing cross-references and preserve qualifiers, scopes, exceptions, units, time anchors and alternatives. Record missing context before proposing an executable rule.'
    else:
        out['instruction']='Use the uploaded Word paragraph and governing passages in the Michigan source packet.'
        out['governing_source_packet']=json.loads((Path(__file__).parent/'michigan_source_packet.json').read_text())
    return out,raw
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('criterion');p.add_argument('site_zip',type=Path);p.add_argument('output',type=Path);p.add_argument('--context-page',type=int,action='append',default=[]);p.add_argument('--review',type=Path);p.add_argument('--onboarding',type=Path);a=p.parse_args()
    o,raw=packet(a.criterion,a.site_zip,a.context_page,a.review,a.onboarding)
    if 'source_pages' in o:
        import fitz
        pdf=fitz.open(stream=raw,filetype='pdf')
        if any(n<1 or n>len(pdf) for n in o['source_pages']):p.error('Context page outside protocol')
    a.output.mkdir(parents=True,exist_ok=False)
    for n in o.get('source_pages',[]):
        pdf[n-1].get_pixmap(matrix=fitz.Matrix(2,2)).save(a.output/f'page-{n}.png')
    (a.output/'packet.json').write_text(json.dumps(o,indent=2,ensure_ascii=False)+'\n')
