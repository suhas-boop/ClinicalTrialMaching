"""Read exported FHIR resources. Queries run against patient-scoped resource and coding indexes."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from convert import HERE

def open_chart(path):
    return sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
def search(db,subject,kind=None,code=None):
    sql='SELECT r.json FROM resource r JOIN membership m USING(type,id) WHERE m.subject=?'
    args=[subject]
    if kind:sql+=' AND r.type=?';args.append(kind)
    if code:
        system,term=code.split('|',1)
        sql+=' AND EXISTS(SELECT 1 FROM coding c WHERE c.type=r.type AND c.id=r.id AND c.system=? AND c.code=?)'
        args.extend((system,term))
    return [json.loads(row[0]) for row in db.execute(sql+' ORDER BY r.type,r.id',args)]
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',type=Path,default=HERE.parent/'round12/export/chart.sqlite')
    p.add_argument('--subject',required=True);p.add_argument('--type');p.add_argument('--code',help='system|code')
    a=p.parse_args()
    with closing(open_chart(a.db)) as db:print(json.dumps(search(db,a.subject,a.type,a.code),indent=2))
