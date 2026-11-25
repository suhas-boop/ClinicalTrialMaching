"""Patient-scoped source search and closed-loop replay of verified record facts."""
import argparse
import base64
from collections import Counter
from contextlib import closing
from datetime import timezone
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3

from evidence_review import screen, screen_snapshot
from recover_records import enrich_packet
from bindings import Snapshot, canonical, contract, instant
from narrative_evidence import supports
from vital_measurements import PATTERNS

STOP=set("the a an and or of to in with for any has is was as at patient patients documented verified evidence current history prior presenting who this does record per due based on before after present whether clinical obtain verify or if under".split())
# Retrieval vocabulary only. These terms cannot establish a finding.
ALIASES={
 "heart rate":"HR pulse tachycardic bradycardic", "respiratory rate":"RR respirations tachypneic tachypnea",
 "paco2":"arterial blood gas ventilation","renal":"kidney creatinine","serum creatinine":"creatinine renal",
 "hypertension":"hypertensive blood pressure","skin":"cutaneous ulcer lesion wound","ulcer":"lesion wound cutaneous",
 "leishmania":"leishmaniasis","ct":"tomography scan imaging","gcs":"Glasgow coma score",
 "laparotomy":"operative surgery abdominal surgical","catheterization":"catheter access arterial venous",
 "consent":"guardian signature assent proxy","hemorrhage":"bleeding hematoma","bleeding":"hemorrhage",
 "cognitive":"memory mental assessment","metastatic":"metastases metastasis","wheezing":"asthma",
 "asthma":"wheezing wheeze","psychiatric":"psychiatry","antipsychotic":"medications psychotropic",
 "depressive":"depression depressed","pregnant":"pregnancy gestation","postmenopausal":"menopause amenorrhea",
 "antifungal":"aspergillosis azole voriconazole","blood dyscrasia":"leukopenia thrombocytopenia cytopenia",
 "angina":"chest pain ischemia","trauma":"injury accident fall","corticosteroids":"prednisone steroids",
 "suicidal":"suicide","inr":"prothrombin anticoagulation","dyspnea":"shortness breath","chest tube":"thoracostomy",
 "copd":"pulmonary emphysema","qt":"qtc electrocardiogram","cns":"cerebral neurologic","infection":"infectious sepsis",
 "ct pulmonary":"lung nodule","neurodevelopmental":"developmental disability","gastric":"stomach",
 "oral medication":"swallow tolerance","laparotomy required":"operative indication","meningeosis":"meningeal",
 "extubation":"intubated ventilation","collision":"accident bike bicycle","thyroid":"thyroidectomy thyroidal"}
DB_SCHEMA="""
CREATE TABLE IF NOT EXISTS docs (
  id INTEGER PRIMARY KEY, patient TEXT NOT NULL, logical TEXT NOT NULL, available TEXT NOT NULL,
  digest TEXT NOT NULL, version TEXT NOT NULL, status TEXT NOT NULL, kind TEXT NOT NULL,
  links TEXT NOT NULL, episode TEXT, encounter TEXT, source_date TEXT, UNIQUE(logical,version), UNIQUE(logical,available));
CREATE INDEX IF NOT EXISTS doc_scope ON docs(patient,logical,available DESC);
CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(body, doc UNINDEXED, loc UNINDEXED, tokenize='porter unicode61');
CREATE TABLE IF NOT EXISTS resources (
  patient TEXT, logical TEXT, version TEXT, available TEXT, payload TEXT,
  PRIMARY KEY(logical,version), UNIQUE(logical,available));
CREATE INDEX IF NOT EXISTS resource_patient ON resources(patient,available);
"""
def utc(s):
    return instant(s).astimezone(timezone.utc).isoformat(timespec="microseconds")

def sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()

def connect(path):
    db=sqlite3.connect(path);db.row_factory=sqlite3.Row;db.executescript(DB_SCHEMA)
    return db

def add_document(db,patient,logical,version,available,kind,parts,links,*,status="current",episode=None,encounter=None,source_date=None):
    if not re.fullmatch(r"Patient/[A-Za-z0-9.-]+",patient) or not version or not logical:
        raise ValueError("Scoped document identity required")
    signature=sha([patient,kind,parts,links,status,episode,encounter,source_date])
    at=utc(available)
    old=db.execute("SELECT * FROM docs WHERE logical=? AND version=?",(logical,version)).fetchone()
    if old:
        if old["digest"]!=signature or old["available"]!=at:raise ValueError("Conflicting document version")
        return
    if db.execute("SELECT 1 FROM docs WHERE logical=? AND patient<>?",(logical,patient)).fetchone():
        raise ValueError("Document identity reused by a different patient")
    new=db.execute("INSERT INTO docs(patient,logical,available,digest,version,status,kind,links,episode,encounter,source_date) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (patient,logical,at,signature,version,status,kind,json.dumps(links),episode,encounter,source_date))
    db.executemany("INSERT INTO passages(body,doc,loc) VALUES(?,?,?)",[(body,new.lastrowid,loc) for loc,body in parts if body.strip()])

def latest(patient,at):
    return ("""WITH visible AS (SELECT *, row_number() OVER(PARTITION BY logical ORDER BY available DESC) AS n
               FROM docs WHERE patient=? AND available<=?) """,[patient,utc(at)])

def search(db,patient,at,query,*,encounter=None,episode=None,limit=5,kind=None,expand_aliases=True):
    if not 1<=limit<=100:raise ValueError("Limit must be between 1 and 100")
    q=" ".join(re.findall(r"[a-z0-9]+",query.lower()))
    words=set(q.split())-STOP
    for phrase,expansion in (ALIASES.items() if expand_aliases else ()):
        if re.search(r"\b"+re.escape(phrase)+r"\b",q):words.update(expansion.split())
    words=sorted(w for w in words if len(w)>1 and not w.isdigit())[:100]
    if not words:return []
    prefix,params=latest(patient,at)
    sql="""SELECT v.logical,v.version,v.digest,v.kind,v.links,v.encounter,v.episode,v.source_date,passages.loc,passages.body,bm25(passages) AS rank
           FROM passages JOIN visible v ON v.id=passages.doc
           WHERE v.n=1 AND v.status='current' AND passages MATCH ?"""
    params.append(" OR ".join('"'+w+'"' for w in words))
    for column,value in [("encounter",encounter),("episode",episode)]:
        if value:sql+=f" AND (v.{column} IS NULL OR v.{column}=?)";params.append(value)
    if kind:sql+=" AND v.kind=?";params.append(kind)
    rows=db.execute(prefix+sql+" ORDER BY rank,v.logical,passages.rowid LIMIT ?",[*params,limit])
    return [{"source":r["logical"],"version":r["version"],"digest":r["digest"],"kind":r["kind"],
             "links":json.loads(r["links"]),"encounter":r["encounter"],"episode":r["episode"],"source_date":r["source_date"],"locator":r["loc"],"passage":r["body"]} for r in rows]

def stats(db,patient,at):
    prefix,params=latest(patient,at)
    rows=db.execute(prefix+"""SELECT kind,count(*) AS total,
      sum(EXISTS(SELECT 1 FROM passages WHERE doc=v.id)) AS readable
      FROM visible v WHERE n=1 AND status='current' GROUP BY kind""",params)
    return {r["kind"]:{"documents":r["total"],"readable":r["readable"]} for r in rows}

def attachment_pages(file,expected,mime):
    raw=file.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:
        raise ValueError("Attachment bytes disagree with the pinned source digest")
    if mime=="text/plain":
        return [raw.decode("utf-8")]
    if mime=="application/pdf":
        from pypdf import PdfReader
        return [page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages]
    return []

def chart_export(db,data,*,attachments=None,available_at=None,missing=None):
    if attachments is not None and not available_at:
        raise ValueError("Supply the time at which retrieved attachment bytes became available")
    if available_at:utc(available_at)
    people={(p["clinic_id"],p["case_id"]):"Patient/"+p["fhir_id"] for p in data["emr_patients"]}
    records={}
    for row in data["emr_chart_records"]:
        r=row["payload"];key=(row["clinic_id"],row["case_id"],r["resourceType"]+"/"+r["id"])
        if key in records and records[key]!=r:raise ValueError("Reconcile duplicate report identity")
        records[key]=r
    result=Counter()
    for d in data["emr_chart_documents"]:
        scope=(d["clinic_id"],d["case_id"]);patient=people[scope];links=d["source_refs"]
        if not links or not all(isinstance(x,str) and x.startswith("DiagnosticReport/") and
                records.get((*scope,x),{}).get("subject",{}).get("reference")==patient for x in links):
            raise ValueError("Unverified chart document identity or source link")
        reports=[records[(*scope,x)] for x in links]
        visits={r["encounter"]["reference"] for r in reports if r.get("encounter",{}).get("reference")}
        if len(visits)>1:raise ValueError("Conflicting encounters in linked chart reports")
        parts=[]
        if d["text_status"]=="ready":
            for i,page in enumerate(d["text"] or []):
                if isinstance(page,str):
                    for j,line in enumerate(page.splitlines()):
                        if line.strip():parts.append((f"page {i+1} line {j+1}",line.strip()))
        logical="chart/"+sha([*scope,d["id"]])
        # Use export update time rather than backdating newly available text to service date.
        status="current" if all(r.get("status") in {"final","amended","corrected","appended"} for r in reports) else "withheld"
        at=max([utc(d["updated_at"])]+[utc(r["issued"]) for r in reports if r.get("issued")])
        add_document(db,patient,logical,at,at,d["category"],parts,links,
                     status=status,encounter=next(iter(visits),None),source_date=d["document_date"])
        if status!="current":
            result["withheld"]+=1
            continue
        if parts:
            result["current_readable"]+=1
            continue
        pinned=d.get("sha256","").lower()
        if not re.fullmatch(r"[a-f0-9]{64}",pinned):
            raise ValueError("Missing original attachment fingerprint")
        newest=db.execute("SELECT version,available FROM docs WHERE logical=? ORDER BY available DESC LIMIT 1",(logical,)).fetchone()
        if newest["version"]!=at:
            if newest["version"].startswith("attachment-"+pinned+"-"):
                result["already_hydrated"]+=1
            else:
                result["superseded"]+=1
            continue
        recovered=[]
        if attachments is not None:
            path=Path(attachments)/pinned
            if path.is_file():
                pages=attachment_pages(path,pinned,d["content_type"])
                recovered=[(f"page {i} line {j}",line.strip()) for i,page in enumerate(pages,1)
                           for j,line in enumerate(page.splitlines(),1) if line.strip()]
        if recovered:
            when=utc(available_at)
            if when<=at:raise ValueError("Retrieved attachment availability must follow the indexed metadata")
            add_document(db,patient,logical,"attachment-"+pinned+"-"+when,when,d["category"],recovered,
                         links,status=status,encounter=next(iter(visits),None),source_date=d["document_date"])
            result["hydrated"]+=1
        else:
            result["current_unreadable"]+=1
            if missing is not None:
                missing.append(dict(patient=patient,document=logical,export_document_id=d["id"],
                                    sha256=pinned,content_type=d["content_type"],report_references=links))
    return dict(result)

def import_bundle(db,bundle):
    if bundle.get("resourceType")!="Bundle" or bundle.get("type")!="collection":
        raise ValueError("A versioned FHIR collection is required")
    n=0
    for e in bundle["entry"]:
        r=e["resource"];typ=r["resourceType"]
        if typ not in {"DocumentReference","Observation"}:continue
        patient=r["subject"]["reference"];logical=typ+"/"+r["id"];version=r["meta"]["versionId"]
        at=utc(r["meta"]["lastUpdated"])
        if db.execute("SELECT 1 FROM resources WHERE logical=? AND patient<>?",(logical,patient)).fetchone():
            raise ValueError("Resource identity reassigned to different patient")
        payload=canonical(r).decode()
        old=db.execute("SELECT payload FROM resources WHERE logical=? AND version=?",(logical,version)).fetchone()
        if old and old[0]!=payload:raise ValueError("Conflicting resource version")
        if not old:db.execute("INSERT INTO resources VALUES(?,?,?,?,?)",(patient,logical,version,at,payload));n+=1
        if typ=="DocumentReference":
            parts=[]
            for i,c in enumerate(r.get("content",[])):
                attachment=c.get("attachment",{})
                if attachment.get("contentType")=="text/plain" and attachment.get("data"):
                    body=base64.b64decode(attachment["data"],validate=True).decode()
                    parts.extend((f"attachment {i+1} line {j+1}",s) for j,s in enumerate(body.splitlines()))
            encounters=[a["reference"] for a in r.get("context",{}).get("encounter",[]) if a.get("reference")]
            status=r["status"] if len(set(encounters))<=1 else "withheld"
            add_document(db,patient,logical,version,max(at,utc(r["date"])) if r.get("date") else at,
                         "Clinical document",parts,[logical+"/_history/"+version],status=status,encounter=next(iter(encounters),None))
    return n

# These ordered hints guide a record search. A family name never supplies a fact.
# Prefer the evidence being asked for (access, ability, reaction, procedure)
# before matching words that merely describe the treatment or disease context.
FAMILIES = [
    ("screening logistics or social work record",
     r"\btravel (?:for|to|from)|\bgeograph\w* (?:inaccessib|access)|\bsocial insurance\b"),
    ("clinical or historical assessment",
     r"\b(?:can|cannot|unable to|able to|ability to) (?:take|swallow|retain|tolerate) (?:an? )?oral\b"),
    ("allergy record", r"hypersensitiv|allerg"),
    ("radiation treatment record", r"\birradiation\b|\bradiotherap\w*\b|\bradiation (?:therapy|treatment)\b"),
    ("nuclear medicine treatment record", r"\bradio(?:active ?iodine|iodine) (?:therapy|treatment)\b"),
    ("MRI safety screening record", r"\bmri (?:metal|safety|implant) screen"),
    ("specimen or biobank record", r"\baliquot (?:available|suitable)|\bspecimen (?:available|suitable)"),
    ("laboratory report", r"\baliquot with .*\bresult\b|\b(?:paco2|inr|ogtt|ivgtt)\b|"
                          r"creatinine|celiac serology|thyroid peroxidase antibod|"
                          r"parasites per ml|species on microscopy"),
    ("vital-sign flowsheet", r"heart rate|respiratory rate|hemodynamically unstable"),
    ("imaging report", r"\bct\b|head ct|mri|pulmonary nodule"),
    ("prior medication and administration record",
     r"\b(?:administered|antifungal|anticoagulation|corticosteroids|medication|drug)\b|"
     r"\blipid lowering regimen\b|\b(?:past|current|prior|previous|ongoing|receiving)\b.{0,32}\btreatment\b|"
     r"\blipid lowering treatment\b"),
    ("wound assessment", r"cutaneous ulcer"),
    ("procedure or operative record", r"laparotomy|catheter|surgery|resection|chest tube"),
    ("neurology assessment", r"seizure|neurologic|impaired consciousness|cognitive|cns|neurodevelopment|\bcsh\b"),
    ("injury or emergency assessment", r"collision|injured|traumatic|trauma|preinjury|\bgcs\b|"
                                      r"\bindex (?:incident|injury)\b|surgical abdomen"),
    ("consent or authorization record", r"consent"),
    ("critical-care or respiratory record", r"ventilation|extubation|shock|ards|asthma|copd|respiratory distress"),
    ("reproductive history", r"pregnan|childbearing|contraception|menopaus|breastfeed|menstrual|"
                             r"menorrhagia|uterine fibroid|in protocol women population"),
    ("birth or neonatal record", r"gestation at birth|gestational age at birth"),
    ("cardiology or ECG record", r"angina|ischemia|arrhythmia|heart failure|hypertension|\bqt\b|\bmi\b"),
    ("behavioral health assessment", r"suicidal|depress"),
    ("oncology or pathology record", r"malignancy|carcinoma|\bcancer\b|life expectancy|\b(?:who|ecog) performance status"),
    ("infectious disease assessment", r"(?<!non)infection|tuberculosis|\bhiv\b|immunodeficiency|\bmalaria\b"),
    ("hematology assessment", r"blood dyscrasia|coagulopathy|bone marrow failure|history of bleeding"),
    ("admission or transfer record", r"hospital admission|transferred to observation unit"),
]


def record_family(scope):
    text = scope.replace("_", " ").lower()
    return next((label for label, pattern in FAMILIES if re.search(pattern, text)),
                "clinical or historical assessment")


def get_resources(db,patient,at):
    return [json.loads(r[0]) for r in db.execute(
            "SELECT payload FROM resources WHERE patient=? AND available<=? ORDER BY logical,available",
            (patient,utc(at)))]

def native_vitals(snap,spec,key):
    """Trusted dedicated vitals sheets. A search hit alone never binds text to a rule."""
    if not supports(key,spec) or key not in {"heart_rate","respiratory_rate"}:return None
    findings=[]
    for d in snap.current.values():
        if (d.get("resourceType")!="DocumentReference" or d.get("subject",{}).get("reference")!=snap.patient or
            not any(c.get("system")=="urn:pocketmd:research:document-type:v1" and c.get("code")=="screening-vitals"
                    for c in d.get("type",{}).get("coding",[]))):continue
        ctx=d.get("context",{})
        if [x.get("reference") for x in ctx.get("encounter",[])]!=[snap.encounter] or [x.get("reference") for x in ctx.get("related",[])]!=[snap.episode]:continue
        if d.get("status")=="entered-in-error" or d.get("status")=="superseded":continue
        if (d.get("status")!="current" or d.get("docStatus")!="final" or d.get("modifierExtension") or d.get("implicitRules") or
            not set(snap.registry.get("record",[])).intersection(a.get("reference") for a in d.get("author",[]))):
            return (None,"MISSING_DATA",[],"Verify the current screening vitals document.")
        try:
            start,end=(instant(ctx["period"][t]) for t in ("start","end"))
            visit_start=instant(snap.current[snap.encounter]["period"]["start"])
            if not visit_start<=start<=end<=instant(d["date"])<=snap.at:continue
            # Accept a dedicated machine-readable sheet only. Free prose, carry-forward
            # headers, unsupported MIME parts and ambiguous lines require verification.
            for i,c in enumerate(d["content"]):
                a=c["attachment"]
                if a.get("contentType")!="text/plain" or not a.get("data"):
                    raise ValueError("Unreadable measurement content")
                body=base64.b64decode(a["data"],validate=True).decode().splitlines()
                for j,line in enumerate(body):
                    if not line.strip():continue
                    matched=[(name,matcher.fullmatch(line.strip())) for name,matcher in PATTERNS.items()]
                    values=[(name,int(m[1])) for name,m in matched if m]
                    if len(values)!=1:raise ValueError("Ambiguous measurement line")
                    name,value=values[0]
                    if name==key:
                        if (value<spec.get("minimum",float("-inf")) or value>spec.get("maximum",float("inf"))
                                or value<=spec.get("exclusiveMinimum",float("-inf"))):
                            raise ValueError("Value outside the contract")
                        ref=f"DocumentReference/{d['id']}/_history/{d['meta']['versionId']}#attachment={i+1}&line={j+1}"
                        findings.append((value,ref))
        except (KeyError,ValueError,TypeError):
            return (None,"MISSING_DATA",[],"Verify the source and collection period of the screening vitals.")
    if not findings:return None
    refs=sorted({ref for _,ref in findings})
    if len({v for v,_ in findings})!=1:return (None,"MISSING_DATA",refs,"Reconcile different source values.")
    return (findings[0][0],None,refs,"Explicit measurement in the verified screening vitals sheet.")

def retrieve(db,rules,packet,study,version,limit=5):
    ctx=packet["context"]
    before=screen(rules,packet,study,version)
    base=Snapshot(packet["bundle"],ctx,study,version)
    resources=get_resources(db,base.patient,ctx["as_of"])
    collection={"resourceType":"Bundle","type":"collection","entry":[{"resource":r} for r in resources]}
    enriched,added=enrich_packet(rules,packet,collection,study,version)
    # Trusted vitals sheets have their own clinical scope validator and need not be referenced
    # by a materialized normalized Observation. Preserve all visible versions including withdrawals.
    extra=[r for r in resources if r["resourceType"]=="DocumentReference"]
    bundle={**enriched["bundle"],"entry":enriched["bundle"]["entry"]+[{"resource":r} for r in extra]}
    snap=Snapshot(bundle,ctx,study,version)
    for rule in rules.values():
        for k,spec in rule["facts"].items():
            code=contract(spec)
            if code in snap.enabled:
                fact=native_vitals(snap,spec,k)
                if fact is not None:snap.native[code]=fact
    after=screen_snapshot(rules,snap,ctx,study,version)
    lookups=[]
    all_requests={q["id"]:q for q in before["requests"]+after["requests"]}
    for q in all_requests.values():
        if q["route"]!="retrieve_record":continue
        text=q["request"];family=record_family(text)
        scope=[study,version,snap.patient,snap.encounter,snap.episode,ctx["as_of"],family]
        longitudinal=bool(re.search(r"\b(?:prior|previous|history|ever|previously|historical|lookback)\b",
                                    text.lower().replace("_"," ")))
        hits=search(db,snap.patient,ctx["as_of"],text,encounter=None if longitudinal else snap.encounter,
                    episode=snap.episode,limit=limit)
        lookups.append({"request_id":q["id"],"source_request_id":sha(scope),"criteria":q["criteria"],
                        "needed":text,"search_scope":"episode history" if longitudinal else "screening encounter","suggested_record":family,"passages":hits})
    return {"before":{k:v["state"] for k,v in before["criteria"].items()},"after":after["criteria"],
            "added_versions":added,"lookups":lookups,"remaining_requests":after["requests"],"work":after["work"],
            "source_inventory":stats(db,snap.patient,ctx["as_of"])}


def read(path):return json.loads(Path(path).read_text())

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest="cmd",required=True)
    for name in ("import-export","import-bundle","search","screen"):
        p=subs.add_parser(name);p.add_argument("--index",required=True)
        if name=="import-export":
            p.add_argument("--attachment-dir",type=Path,help="Local original files named by their SHA-256")
            p.add_argument("--available-at",help="Offset-qualified retrieval time for supplied attachments")
            p.add_argument("--missing-manifest",type=Path,help="Private output listing exact source attachments to request")
        if name.startswith("import"):p.add_argument("file")
        elif name=="search":
            p.add_argument("--patient",required=True);p.add_argument("--as-of",required=True);p.add_argument("--query",required=True)
        else:
            for k in ("packet","rules","study","version"):p.add_argument("--"+k,required=True)
    args=parser.parse_args()
    if not args.cmd.startswith("import") and not Path(args.index).is_file():
        parser.error("Import the source archive before querying this index.")
    with closing(connect(args.index)) as db,db:
        if args.cmd=="import-export":
            missing=[]
            out=chart_export(db,read(args.file),attachments=args.attachment_dir,available_at=args.available_at,missing=missing)
            if args.missing_manifest:
                args.missing_manifest.write_text(json.dumps(missing,indent=2)+"\n")
        elif args.cmd=="import-bundle":out={"new_resources":import_bundle(db,read(args.file))}
        elif args.cmd=="search":out=search(db,args.patient,args.as_of,args.query)
        else:out=retrieve(db,read(args.rules),read(args.packet),args.study,args.version)
    print(json.dumps(out,indent=2))

if __name__=="__main__":main()
