"""Verify supplemental teaching-case interpretations against the released benchmark.

The spreadsheet has suggestions for differential diagnoses, tests and treatments.
Store them for source review. None of those columns asserts an established diagnosis,
a completed test, receipt of treatment or any numerical vital sign.
"""
import argparse
import hashlib
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKBOOK_DIGEST = '65c7faf89e7cf262c83e7d4e548ba47e738997e6a3c68258c090e29a46cd496b'
URL = 'https://trec.nist.gov/data/clinical/answers-2014.xlsx'
NIST = 'https://trec.nist.gov/data/clinical2014.html'
N = {'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def workbook_rows(workbook):
    if hashlib.sha256(workbook.read_bytes()).hexdigest() != WORKBOOK_DIGEST:
        raise ValueError('Unexpected supplemental source SHA-256')
    with zipfile.ZipFile(workbook) as archive:
        strings = ET.fromstring(archive.read('xl/sharedStrings.xml'))
        shared = [''.join(t.text or '' for t in s.findall('.//s:t',N)) for s in strings]
        page = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        rows = []
        for row in page.findall('s:sheetData/s:row', N):
            cells = {}
            for c in row.findall('s:c', N):
                value = c.findtext('s:v','',N)
                col = re.fullmatch(r'([A-Z]+)\d+',c.get('r'))[1]
                cells[col] = shared[int(value)] if c.get('t') == 's' else value
            rows.append((row.get('r'), cells))
    header = rows[0][1]
    if [header[k].strip() for k in ('A','B','C','D','E','F','G')] != [
        'number','type','description','summary','differential diagnosis','tests','treatments']:
        raise ValueError('Unrecognized clinical assertion types in workbook')
    return rows[1:]


def review(benchmark, workbook):
    sys.path.insert(0, str(benchmark/'round14/organizer_sources'))
    from source_join import join, pinned, normalized, topic_index
    identified = join(benchmark)
    topics = topic_index(pinned(benchmark/'round7/2014.xml'))
    subjects = {s['case']:s['subject'] for s in json.loads((benchmark/'round9/export/cases.json').read_text())}
    reports = {}
    for row_id, row in workbook_rows(workbook):
        num = row['A']
        pid = 'sigir-2014'+num
        topic = topics[num]
        if (row['B'] != topic.get('type') or normalized(row['C']) != normalized(topic.findtext('description'))
                or normalized(row['D']) != normalized(topic.findtext('summary'))):
            raise ValueError('Narratives disagree at worksheet row '+row_id)
        if pid not in identified:
            continue
        if pid in reports:
            raise ValueError('Duplicated case identity')
        reports[pid] = dict(subject=subjects[pid], sheet='Sheet1', row=int(row_id),
                            subject_source_sha256=identified[pid]['source_note_sha256'],
                            differential=row.get('E','').strip(), differential_cell='E'+row_id,
                            context='retrospective educational interpretation',
                            promoted_clinical_assertions=[])
    return dict(source_url=URL, source_description=NIST, source_sha256=WORKBOOK_DIGEST, n_patients_or_groups=len(reports),
                source_use='Review only. A listed diagnosis is a differential, a proposed test has no result, and a proposed treatment has no administration.',
                records=reports)


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('benchmark',type=Path)
    cli.add_argument('output',type=Path)
    args = cli.parse_args()
    report = review(args.benchmark, HERE/'answers-2014.xlsx')
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(report['n_patients_or_groups'], 'verified subject joins')
