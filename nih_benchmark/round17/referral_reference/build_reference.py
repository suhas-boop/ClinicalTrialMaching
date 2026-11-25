"""Extract published referral judgments for an existing patient–study cohort; reads no model results."""
import argparse
import csv
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parent
SOURCE='https://data.csiro.au/dap/ws/v2/collections/22333/data/49692372'
TOPICS='https://data.csiro.au/dap/ws/v2/collections/22333/data/49692376'
DOI='https://doi.org/10.4225/08/58e2e83d92c2b'
NIH_ROOT='https://raw.githubusercontent.com/ncbi-nlp/TrialGPT/1b3242cd50c153a9c324661d4a0bd94fc68a4226/dataset/sigir/'
PAPER='https://doi.org/10.1145/2911451.2914672'
PINS={'v4_qrels-clinical_trials.txt': 'f0b9aa8aa22b4c4eb5405c0bd2dc8220ac43a9c1d75e08782a410324270ce45e', 'v4_topics-2014_2015-description.topics': 'f150a44a5d6226734aead0e1daa555876159615e9248a05dc093fca48e1e2c3e', 'nih.tsv': '5298efb4859cfcdfe2cae5748eb1df1d4970c383c35a87e20145d1b3c25ea8ab', 'nih_queries.jsonl': '97ce3172bf6f80f3a5ac81371b83c9f031eccb243004b12cb5fd0015d372aa9b'}
NAMES={'0':'would_not_refer','1':'consider_referral_after_further_investigation','2':'highly_likely_to_refer'}
def sha(content):return hashlib.sha256(content).hexdigest()
def read_json(path):return json.loads(path.read_text())

def run(benchmark,inputs,out):
    for name,expected in PINS.items():
        if sha((inputs/name).read_bytes())!=expected: raise ValueError('Published reference changed: '+name)
    sys.path.insert(0,str(benchmark/'round14/organizer_sources'))
    from source_join import frozen_description,description_match
    subjects=read_json(benchmark/'round9/notes.json')
    ids=read_json(benchmark/'round9/assignments.json')
    selected=sorted({(r['patient'],r['study']) for r in ids})
    if len(selected)!=68:raise ValueError('Unexpected pair population')
    official=inputs/'v4_qrels-clinical_trials.txt'
    topics=inputs/'v4_topics-2014_2015-description.topics'
    nih=inputs/'nih.tsv'
    nihtopics=inputs/'nih_queries.jsonl'
    pairs={}
    for line,raw in enumerate(official.read_text().splitlines(),1):
        topic, iteration, trial, grade=raw.split()
        if grade not in NAMES or iteration!='0' or (topic,trial) in pairs: raise ValueError('Unexpected original qrels format')
        pairs[(topic,trial)]=[grade,line]
    cases=re.findall(r'<NUM>([0-9]+)</NUM>\s*<TITLE>(.*?)\s*</TOP>',topics.read_text(),re.S)
    profiles={p:html.unescape(text.strip()) for p,text in cases}
    if len(cases)!=len(profiles) or len(profiles)!=60: raise ValueError('Unexpected source topic IDs')
    nh={}
    with nih.open() as f:
        for line,r in enumerate(csv.DictReader(f,delimiter='\t'),2):
            key=(r['query-id'],r['corpus-id'])
            if key in nh: raise ValueError('Duplicate transformed qrel')
            nh[key]=(r['score'],line)
    nihprofiles={r['_id']:r['text'] for r in (json.loads(line) for line in nihtopics.read_text().splitlines())}
    for (pat,study),(grade,_) in nh.items():
        if pairs[(pat.removeprefix('sigir-'),study)][0]!=grade: raise ValueError('Source disagreement')
    rows=[]
    for patient,study in selected:
        target=patient.removeprefix('sigir-')
        lhs=frozen_description(subjects[patient])
        method=description_match(lhs,profiles[target])
        if patient in nihprofiles:
            description_match(lhs,nihprofiles[patient])
        grade,ln=pairs.get((target,study),('',''))
        transformed,nline=nh.get((patient,study),('',''))
        rows.append(dict(patient=patient,study=study,original_topic_id=target,
                         frozen_note_sha256=sha(subjects[patient].encode()),topic_text_sha256=sha(profiles[target].encode()),
                         topic_join=method,reference_status='JUDGED' if grade else 'UNJUDGED',
                         csiro_referral_grade=grade,csiro_grade_meaning=NAMES.get(grade,''),csiro_qrels_line=ln,
                         csiro_version_doi=DOI,csiro_source=SOURCE,
                         nih_release_grade=transformed,nih_qrels_line=nline))
    out.mkdir(parents=True,exist_ok=True)
    dest=out/'sigir_referral_reference.csv'
    with dest.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    metadata=dict(source_title='A Test Collection for Matching Patient to Clinical Trials',
        authors='Bevan Koopman and Guido Zuccon',assessment_methods=PAPER,
        original_collection='https://doi.org/10.4225/08/5714557510C17',
        version_history='https://data.csiro.au/dap/ws/v2/collections/17152/versions',
        selected_source={'version':4,'published':'2017-04-04','doi':DOI,'file':SOURCE,
                         'file_sha256':sha(official.read_bytes()),'records':len(pairs),
                         'description_file':TOPICS,'description_file_sha256':sha(topics.read_bytes())},
        rights=read_json(inputs/'v4_metadata.json')['rights'],license='CC BY-SA 4.0 https://creativecommons.org/licenses/by-sa/4.0/',
        adaptation='Subset of published patient–study referral judgments with renamed columns, topic and protocol IDs, and source line locators.',
        clinical_meaning=NAMES,
        missing_grade='No judgment for that topic–trial pair in that release. Leave blank and exclude from judged denominators.',
        design='Medical assessors rated referral likelihood for a ranked pool with a finite assessment budget. These are trial-level referral preference judgments, without independent confirmation of eligibility or enrollment.',
        cohort='Existing unique patient–study assignments from the 134 criterion annotations. This convenience sample is not a representative sample of the full relevance collection.',
        identity='Join the suffix of the sigir- identifier to the exact NUM in the organizers’ topics file, preserving its original year and unpadded number. The full normalized patient description was verified for every selected subject.',
        assignments_sha256=sha((benchmark/'round9/assignments.json').read_bytes()),selected_pairs=len(rows),
        selected_patients=len({r['patient'] for r in rows}),selected_studies=len({r['study'] for r in rows}),
        selected_counts=dict(Counter(r['csiro_referral_grade'] or 'UNJUDGED' for r in rows)),
        transformed_release={'file':NIH_ROOT+'qrels/test.tsv','file_sha256':sha(nih.read_bytes()),
            'topics':NIH_ROOT+'queries.jsonl','topics_sha256':sha(nihtopics.read_bytes()),'records':len(nh),
            'agreements_on_overlapping_pairs':len(nh),'selected_pairs_covered':sum(r['nih_release_grade']!='' for r in rows),
            'absent_original_topic_ids':sorted({topic for topic,_ in pairs if ('sigir-'+topic) not in nihprofiles}),
            'comparison':'The transformed release omits the original group topic. The source grade remains available for those rows and still refers to the group vignette.'},
        reference_csv_sha256=sha(dest.read_bytes()))
    (out/'reference_provenance.json').write_text(json.dumps(metadata,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--benchmark',required=True,type=Path);p.add_argument('--inputs',default=ROOT,type=Path)
    p.add_argument('--out',default=ROOT,type=Path);args=p.parse_args();run(args.benchmark,args.inputs,args.out)
