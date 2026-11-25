"""Pick ten patients by stable hash; withhold every other row for these patients from development."""
import hashlib, json, sys
from pathlib import Path
import duckdb

out = Path(__file__).resolve().parent
db = duckdb.connect()
cursor = db.execute("""SELECT annotation_id, patient_id, trial_id, criterion_type, criterion_text, note
                       FROM read_parquet(?) WHERE NOT training ORDER BY annotation_id""", [sys.argv[1]])
cols = [x[0] for x in cursor.description]
rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
rank = lambda p: hashlib.sha256(('PocketMD-NIH-pilot-v1|' + p).encode()).digest()
patients = set(sorted({r['patient_id'] for r in rows}, key=rank)[:10])
chosen = [r for r in rows if r['patient_id'] in patients]
(out/'blind.json').write_text(json.dumps(chosen, indent=2))
for r in chosen: print(r['annotation_id'],r['criterion_type'],r['criterion_text'])
