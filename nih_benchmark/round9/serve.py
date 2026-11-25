"""Local read-only FHIR R4 endpoint for the converted TrialGPT data."""
import argparse,json
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs,urlencode
from wsgiref.simple_server import make_server
from chart import open_chart
from convert import HERE

TYPES={'Patient','Group','Condition','Procedure','Observation','MedicationStatement','FamilyMemberHistory','Device','Provenance','DocumentReference'}
PATIENT_PARAM={'Observation','Condition','Procedure','MedicationStatement','FamilyMemberHistory'}
SUBJECT_PARAM={'Observation','Condition','Procedure','MedicationStatement','DocumentReference'}
CODE_PARAM={'Observation','Condition','Procedure','MedicationStatement'}
def allowed(t):
    a={'_id'}
    if t in PATIENT_PARAM:a.add('patient')
    if t in SUBJECT_PARAM:a.add('subject')
    if t in CODE_PARAM:a.add('code' if t!='MedicationStatement' else 'medication')
    return a
def error(code,msg):
    return {'resourceType':'OperationOutcome','issue':[{'severity':'error','code':code,'diagnostics':msg}]}
def app(db_path):
    def handle(env,send):
        def reply(status,obj):
            data=json.dumps(obj,ensure_ascii=False).encode();send(status,[('Content-Type','application/fhir+json; charset=utf-8'),('Content-Length',str(len(data)))]);return [data]
        if env['REQUEST_METHOD']!='GET':return reply('405 Method Not Allowed',error('not-supported','Read-only endpoint'))
        parts=env['PATH_INFO'].strip('/').split('/')
        if parts[:1]!=['fhir'] or len(parts) not in (2,3):return reply('404 Not Found',error('not-found','Use /fhir/metadata'))
        typ=parts[1]
        if typ=='metadata' and len(parts)==2:
            return reply('200 OK',{'resourceType':'CapabilityStatement','status':'active','date':'2026-11-23','kind':'instance',
                'fhirVersion':'4.0.1','format':['json'],'implementation':{'description':'Local PocketMD TrialGPT research export'},
                'rest':[{'mode':'server','resource':[{'type':t,'interaction':[{'code':'read'},{'code':'search-type'}],
                    'searchParam':[{'name':k,'type':'reference' if k in {'patient','subject'} else 'token'} for k in sorted(allowed(t))]} for t in sorted(TYPES)]}]})
        if typ not in TYPES:return reply('404 Not Found',error('not-found','Unknown resource type'))
        base=env['wsgi.url_scheme']+'://'+env['SERVER_NAME']+':'+env['SERVER_PORT']+'/fhir'
        with closing(open_chart(db_path)) as db:
            if len(parts)==3:
                item=db.execute('SELECT json FROM resource WHERE type=? AND id=?',(typ,parts[2])).fetchone()
                return reply('200 OK',json.loads(item[0])) if item else reply('404 Not Found',error('not-found','Unknown resource'))
            qs=parse_qs(env.get('QUERY_STRING',''),keep_blank_values=True)
            if set(qs)-allowed(typ) or any(len(v)!=1 or not v[0] for v in qs.values()):
                return reply('400 Bad Request',error('not-supported','Unsupported parameter or repetition'))
            sql='SELECT r.json FROM resource r WHERE r.type=?';args=[typ]
            for k,(v,) in qs.items():
                if k=='_id':sql+=' AND r.id=?';args.append(v)
                elif k in {'subject','patient'}:
                    subject=v if '/' in v else 'Patient/'+v
                    if k=='patient' and not subject.startswith('Patient/'):return reply('400 Bad Request',error('invalid','Expected Patient reference'))
                    sql+=' AND EXISTS(SELECT 1 FROM membership m WHERE (m.type,m.id)=(r.type,r.id) AND m.subject=?)';args.append(subject)
                else:
                    pred='c.code=?';vals=[v]
                    if '|' in v:
                        system,code=v.split('|',1);pred='c.system=? AND c.code=?';vals=[system,code]
                    sql+=' AND EXISTS(SELECT 1 FROM coding c WHERE (c.type,c.id)=(r.type,r.id) AND '+pred+')';args+=vals
            rows=[json.loads(r[0]) for r in db.execute(sql+' ORDER BY r.id',args)]
            bundle={'resourceType':'Bundle','type':'searchset','total':len(rows),
                    'link':[{'relation':'self','url':base+'/'+typ+('?' + urlencode(qs,doseq=True) if qs else '')}]}
            if rows:bundle['entry']=[{'fullUrl':base+'/'+typ+'/'+r['id'],'resource':r,'search':{'mode':'match'}} for r in rows]
            return reply('200 OK',bundle)
    return handle
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',type=Path,default=HERE.parent/'round12/export/chart.sqlite');p.add_argument('--port',type=int,default=8765)
    a=p.parse_args()
    with make_server('127.0.0.1',a.port,app(a.db)) as server:server.serve_forever()
