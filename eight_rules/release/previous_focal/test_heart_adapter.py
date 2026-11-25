"""Exercise the native heart-rate binding via the same Snapshot and E17 expression used by the CLI."""
from copy import deepcopy
from pathlib import Path
import json
import unittest

import heart_adapter as heart
import normalized as n


def native_example(rules, value=50):
    packet = n.make_packet(rules, {}, patient='pulse-demo', encounter='screen', stamp='2026-05-02T12:00:00Z')
    participant = {'reference':'Patient/pulse-demo'}
    visit = {'reference':'Encounter/screen'}
    observer = {'reference':'Organization/demo-record'}
    for row in packet['bundle']['entry']:
        row['resource']['meta']['lastUpdated']='2026-04-09T11:00:00Z'
        if row['resource']['resourceType']=='Encounter':
            row['resource']['period']['start']='2026-04-10T10:00:00Z'
    def doc(rid, issued, event=None, when=None):
        result={'resourceType':'DocumentReference','id':rid,'status':'current','subject':dict(participant),
                'author':[dict(observer)],'date':issued,'meta':{'versionId':'1','lastUpdated':issued},
                'identifier':[{'system':n.SOURCE,'value':n.HASH}], 'context':{'encounter':[dict(visit)]},
                'content':[{'attachment':{'contentType':'text/plain','data':'c3ludGhldGljIHNvdXJjZQ=='}}]}
        if event is not None:
            result['type']={'coding':[{'system':heart.EVENT,'code':event}]}
            result['context']['period']={'start':when}
        return result
    consent=doc('main-consent','2026-04-10T10:15:00Z','main-icf-signed','2026-04-10T10:00:00Z')
    cycle=doc('planned-cycle','2026-04-10T11:00:00Z','c1d1-planned','2026-05-01T09:00:00Z')
    report=doc('vitals-report','2026-04-29T10:15:00Z')
    pulse={'resourceType':'Observation','id':'pulse','status':'final','subject':dict(participant),
           'encounter':dict(visit),'performer':[dict(observer)],'derivedFrom':[{'reference':n.ref(report)}],
           'meta':{'versionId':'1','lastUpdated':'2026-04-29T10:15:00Z'},
           'code':{'coding':[{'system':heart.LOINC,'code':heart.PULSE}]},
           'effectiveDateTime':'2026-04-29T10:00:00Z','issued':'2026-04-29T10:15:00Z',
           'valueQuantity':{'system':n.UCUM,'code':'/min','unit':'beats/minute','value':value}}
    packet['bundle']['entry'].extend({'resource':r} for r in [consent,cycle,report,pulse])
    packet['context']['heart_rate_anchors']={'main_consent':n.ref(consent),'cycle1':n.ref(cycle)}
    packet['context']['as_of']='2026-04-30T18:00:00Z'
    return packet


example = native_example


def run_checks(rules):
    rule=rules.get('E17') or rules['106S01-E17']
    key=n.contract(rule['facts']['heart_rate'])
    cases=[]
    def resource(p,rid):
        return next(e['resource'] for e in p['bundle']['entry'] if e['resource']['id']==rid)
    def check(name,p,expected):
        native=heart.derive(rules,p['bundle'],p['context'])
        if expected=='ABSENT':
            assert key not in native,(name,native)
            actual='ABSENT'
        else:
            snapshot=n.Snapshot(p['bundle'],p['context'])
            snapshot.native=native
            outcome=n.evaluate(rule,snapshot)
            actual=outcome['state']
            if expected in ('MET','NOT_MET'):
                refs=outcome['evidence']
                assert all('/_history/' in s for s in refs) and len(refs)>=6 and n.ref(resource(p,'pulse')) in refs, (name,refs)
            assert actual==expected,(name,expected,outcome)
        cases.append(dict(case=name,criterion='E17',expected=expected,actual=actual))
    def measure(p, stamp):
        pulse=resource(p,'pulse')
        pulse.update(effectiveDateTime=stamp,issued=stamp)
        pulse['meta']['lastUpdated']=stamp
        report=resource(p,'vitals-report')
        report['date']=stamp
        report['meta']['lastUpdated']=stamp
    for v,expected in ((49,'NOT_MET'),(50,'MET'),(72,'MET'),(0,'MISSING_DATA'),(-0.1,'MISSING_DATA'),(True,'MISSING_DATA')):
        check(f'standard LOINC pulse value {v}',native_example(rules,v),expected)
    for name,stamp,expected in [
            ('first allowed day after consent','2026-04-10T11:00:00Z','MET'),
            ('same day before consent signature','2026-04-10T09:00:00Z','MISSING_DATA'),
            ('one day before screening opens','2026-04-09T11:00:00Z','MISSING_DATA'),
            ('day before C1D1','2026-04-30T10:00:00Z','MET'),
            ('C1D1 outside screening','2026-05-01T09:00:00Z','MISSING_DATA')]:
        p=native_example(rules);p['context']['as_of']='2026-05-02T12:00:00Z'
        measure(p,stamp);check(name,p,expected)
    p=native_example(rules)
    p['context']['site_zone']='America/Los_Angeles'
    p['context']['as_of']='2026-05-02T12:00:00Z'
    measure(p,'2026-05-01T05:00:00Z');check('local April 30 despite UTC May 1',p,'MET')
    p=native_example(rules)
    p['context']['as_of']='2026-05-02T12:00:00Z'
    cd=resource(p,'planned-cycle');cd['type']['coding'][0]['code']='c1d1-actual'
    cd['date']=cd['meta']['lastUpdated']='2026-05-01T10:00:00Z'
    check('actual cycle time after first dose documented',p,'MET')
    for name,id,mutation,expected in [
        ('another patient has this pulse','pulse',lambda x:x['subject'].update(reference='Patient/other'),'ABSENT'),
        ('another encounter has this pulse','pulse',lambda x:x['encounter'].update(reference='Encounter/other'),'ABSENT'),
        ('unmapped local numeric code','pulse',lambda x:x['code']['coding'][0].update(system='urn:local'),'ABSENT'),
        ('coded heart rate with wrong unit','pulse',lambda x:x['valueQuantity'].update(code='mg'),'MISSING_DATA'),
        ('unverified unit system','pulse',lambda x:x['valueQuantity'].update(system='urn:local'),'MISSING_DATA'),
        ('quantity is a bound only','pulse',lambda x:x['valueQuantity'].update(comparator='<'),'MISSING_DATA'),
        ('untrusted performer','pulse',lambda x:x.update(performer=[{'reference':'Organization/other'}]),'MISSING_DATA'),
        ('untrusted source signer','vitals-report',lambda x:x.update(author=[{'reference':'Practitioner/other'}]),'MISSING_DATA'),
        ('source is another patient','vitals-report',lambda x:x['subject'].update(reference='Patient/other'),'MISSING_DATA'),
        ('source belongs to another encounter','vitals-report',lambda x:x['context']['encounter'][0].update(reference='Encounter/other'),'MISSING_DATA'),
        ('source title without document content or locator','vitals-report',lambda x:x['content'][0].update(attachment={'contentType':'text/plain','title':'Pulse'}),'MISSING_DATA'),
        ('unversioned evidence reference','pulse',lambda x:x['derivedFrom'][0].update(reference='DocumentReference/vitals-report'),'MISSING_DATA'),
        ('preliminary heart rate','pulse',lambda x:x.update(status='preliminary'),'MISSING_DATA'),
        ('date-only pulse','pulse',lambda x:x.update(effectiveDateTime='2026-04-29'),'MISSING_DATA'),
        ('issued after screening snapshot','pulse',lambda x:x.update(issued='2026-05-15T09:00:00Z'),'MISSING_DATA'),
        ('pulse issued before measurement','pulse',lambda x:x.update(issued='2026-04-28T09:00:00Z'),'MISSING_DATA'),
        ('wrong main consent type','main-consent',lambda x:x['type']['coding'][0].update(code='prescreen-icf'),'MISSING_DATA'),
        ('consent source predates actual signature','main-consent',lambda x:x['context']['period'].update(start='2026-04-12T09:00:00Z'),'MISSING_DATA'),
        ('C1D1 anchor belongs to another encounter','planned-cycle',lambda x:x['context']['encounter'][0].update(reference='Encounter/other'),'MISSING_DATA'),
        ('future actual C1D1 mislabelled as completed','planned-cycle',lambda x:x['type']['coding'][0].update(code='c1d1-actual'),'MISSING_DATA'),
        ('oversized screening interval','planned-cycle',lambda x:x['context']['period'].update(start='2026-05-25T09:00:00Z'),'MISSING_DATA')]:
        p=native_example(rules);mutation(resource(p,id));check(name,p,expected)
    p=native_example(rules);del p['context']['heart_rate_anchors'];check('missing C1D1 and main consent',p,'MISSING_DATA')
    p=native_example(rules);p['context']['site_zone']='invalid/zone';check('undefined site date zone',p,'MISSING_DATA')
    p=native_example(rules);p['context']['enabled_contracts']=[];check('disabled local contract',p,'BINDING_HOLD')
    for value,expected in ((51,'MISSING_DATA'),(50,'MET')):
        p=native_example(rules);add=deepcopy(resource(p,'pulse'));add['id']='pulse2';add['valueQuantity']['value']=value
        p['bundle']['entry'].append({'resource':add});check(f'concurrent native pulse {value}',p,expected)
    p=native_example(rules);doc=deepcopy(resource(p,'vitals-report'));doc['meta'].update(versionId='2',lastUpdated='2026-04-30T09:00:00Z')
    p['bundle']['entry'].append({'resource':doc});check('stale source version',p,'MISSING_DATA')
    p=native_example(rules);amended=deepcopy(resource(p,'pulse'));amended['meta'].update(versionId='2',lastUpdated='2026-04-30T09:00:00Z')
    amended['status']='entered-in-error';p['bundle']['entry'].append({'resource':amended});check('withdrawn native pulse',p,'ABSENT')
    p=native_example(rules);p['bundle']['entry'].append({'resource':{'resourceType':'DocumentReference','id':'unrelated'}})
    check('unrelated unversioned document',p,'MET')
    p=native_example(rules);t=n.make_packet(rules,{next(k for k in rules if k in ('E17','106S01-E17')):{'heart_rate':41}},patient='pulse-demo',encounter='screen',stamp='2026-04-29T17:00:00Z')
    p['bundle']['entry']+=t['bundle']['entry'][3:];check('chart and normalized profile disagree',p,'MISSING_DATA')
    return cases


def load():
    for f in (Path(__file__).with_name('sotio_rules.json'),Path(__file__).with_name('rules.json'),Path(__file__).resolve().parents[1]/'authoring'/'exclusions'/'rules.json'):
        if f.exists():
            d=json.loads(f.read_text());return d.get('rules',d)
    raise FileNotFoundError('Rules artifact required')


class TestNativeHeartRate(unittest.TestCase):
    def test_native_contract(self):
        self.assertGreater(len(run_checks(load())),30)


if __name__=='__main__':
    print(len(run_checks(load())),'E17 native FHIR cases passed.')
