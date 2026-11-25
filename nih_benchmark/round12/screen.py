"""Screen an ingested FHIR bundle, query the chart store, or replay the evaluation."""
import argparse
from contextlib import closing
from datetime import date
import json
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
R11=HERE.parent/'round11'
sys.path.insert(0,str(R11))
from match import open_chart,search,screen,replay,read_json,verify

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('export',type=Path,nargs='?',default=HERE/'export')
    p.add_argument('--out',type=Path,default=HERE/'results');p.add_argument('--catalog',type=Path,default=R11/'compiled.json')
    p.add_argument('--subject');p.add_argument('--study');p.add_argument('--criterion');p.add_argument('--bundle',type=Path)
    p.add_argument('--encounter',help='FHIR Encounter/id for a patient-linked, multi-document intake bundle')
    p.add_argument('--review-answer',type=Path)
    p.add_argument('--review-trust',type=Path)
    p.add_argument('--governing-protocol',type=Path)
    p.add_argument('--as-of',type=date.fromisoformat)
    args=p.parse_args();pack=verify(read_json(args.catalog))
    review_inputs = [args.review_answer,args.review_trust,args.governing_protocol,args.as_of]
    if any(review_inputs) and not (all(review_inputs) and args.subject and args.study):
        p.error('Reviewed screening requires the study, subject, answer, trusted reviewer configuration, governing protocol and as-of date.')

    if args.encounter is not None:
        if not (args.bundle and args.study and args.subject and args.subject.startswith('Patient/') and args.encounter.startswith('Encounter/')):
            p.error('Encounter screening requires --bundle, --study, --subject Patient/id and --encounter Encounter/id.')
        if any(review_inputs):
            p.error('Review activation currently supports single-document screening only.')

    if args.subject or args.study or args.criterion or args.bundle:
        if not (args.study and args.subject):p.error('Supply the study and subject')
        if args.bundle:
            items=[e['resource'] for e in read_json(args.bundle)['entry']]
        else:
            with closing(open_chart(args.export/'chart.sqlite')) as db:items=search(db,args.subject)
        if args.encounter is not None:
            sys.path.insert(0,str(HERE.parent/'round14'))
            from record_arrivals import screen_encounter
            result=screen_encounter(items,args.subject,args.encounter,pack,args.study,args.criterion)
        elif args.review_answer:
            sys.path.insert(0,str(HERE.parent / 'round16'))
            from review706.release import screen_reviewed
            envelope = read_json(args.review_answer)
            if not isinstance(envelope, dict):
                p.error('Expected a protocol review answer object.')
            result = screen_reviewed(items,args.subject,pack,args.study,args.criterion,
                    envelope=envelope,trust=read_json(args.review_trust),
                    protocol_bytes=args.governing_protocol.read_bytes(),as_of=args.as_of)
        else:
            result=screen(items,args.subject,pack,args.study,args.criterion)
    else:result=replay(args.export,args.out,pack,R11/'results')
    print(json.dumps(result,indent=2))
