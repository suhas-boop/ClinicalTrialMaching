"""Aggregate private chart index coverage. Run locally with one patient per input export."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'criterion_workbench'))
from record_search import chart_export,connect,search,stats

def inventory(path):
    data=json.loads(path.read_text())
    if len(data['emr_patients'])!=1:raise ValueError('Use a single-patient export')
    patient='Patient/'+data['emr_patients'][0]['fhir_id']
    with closing(connect(':memory:')) as db:
        missing=[]
        disposition=chart_export(db,data,missing=missing)
        at=db.execute('select max(available) from docs').fetchone()[0]
        counts=stats(db,patient,at)
        result=dict(export_rows=sum(disposition.values()),current_documents=sum(v['documents'] for v in counts.values()),
                    current_readable=sum(v['readable'] for v in counts.values()),dispositions=disposition,
                    requested_original_attachments=len(missing))
        result['chart_search']={}
        for query in ['transfusion','INR','filgrastim pegfilgrastim']:
            hits=search(db,patient,at,query,limit=100)
            result['chart_search'][query]={'passages_returned_cap_100':len(hits),'distinct_documents_in_returned_set':len({r['source'] for r in hits})}
        return result
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('exports',nargs='+',type=Path)
    print(json.dumps({f'export_{i}':inventory(path) for i,path in enumerate(p.parse_args().exports,1)},indent=2))
