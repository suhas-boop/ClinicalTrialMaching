"""Screen a released study and add the criterion-level evidence review where supported."""
import argparse
import json
from pathlib import Path
from evidence_review import screen as evidence_screen
from screen_study import screen as released_screen, get_pack, FOCAL


def run(packet, archive=None):
    result = released_screen(packet)
    if result['study'] in FOCAL:
        result['review_mode'] = 'original study-specific evidence trace'
        if archive is not None:
            result['archive_recovery'] = {'status':'unsupported_native_evaluator'}
        return result
    if result['mode']=='historical_version_block':
        result['review_mode'] = 'source version required'
        if archive is not None:
            result['archive_recovery'] = {'status':'historical_version_block'}
        return result
    pack=get_pack(result['study'])
    rules={**pack['rules'],**pack.get('supplemental_rules',{})}
    if archive is not None:
        from recover_records import enrich_packet
        packet, versions = enrich_packet(rules, packet, archive, result['study'], result['protocol_sha256'])
        initial = result
        result = released_screen(packet)
        changes = {}
        for group in ('criteria', 'supplemental'):
            for key, verdict in result.get(group, {}).items():
                previous = initial[group][key]['state']
                if previous != verdict['state']:
                    changes[key] = {'before':previous, 'after':verdict['state'], 'evidence':verdict['evidence']}
        result['archive_recovery'] = {'status':'evaluated', 'new_resource_versions':versions, 'changes':changes}
    review=evidence_screen(rules,packet,result['study'],result['protocol_sha256'])
    for group in ('criteria','supplemental'):
        for k,original in result.get(group,{}).items():
            updated=review['criteria'][k]
            if updated['state']!=original['state'] or updated['evidence']!=original['evidence']:
                raise ValueError('Review disagrees with pinned study evaluation')
            original['partial_evidence']=updated['partial_evidence']
    result['requests']=review['requests']
    result['work']=review['work']
    result['review_mode']='typed evidence review'
    return result


if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('packet',type=Path)
    cli.add_argument('--archive',type=Path,help='Supplemental normalized FHIR collection for this screening')
    args = cli.parse_args()
    archive = json.loads(args.archive.read_text()) if args.archive else None
    print(json.dumps(run(json.loads(args.packet.read_text()), archive),indent=2))
