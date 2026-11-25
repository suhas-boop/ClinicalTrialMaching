"""Engineering adjudication of earlier disagreements, independent of the new test panel."""
import csv,json
from pathlib import Path
root=Path(__file__).resolve().parent
old={int(x['annotation_id']):x for x in csv.DictReader((root.parent/'all_results.csv').open()) if x['expert'] in ('MET','NOT_MET') and x['revised'] not in ('MET','NOT_MET')}
groups={
'No decisive statement in supplied narrative': {
29:'No serum creatinine result or explicit assessment of severe renal impairment.',145:'No assessment of active suicidal ideation.',147:'No documented history or denial of deep brain stimulation.',217:'No statement establishing or denying trauma as the cause of dyspnea.',
396:'No targeted cardiac history, ECG or reliable reconciliation of the listed conditions.',397:'No baseline or repeat QTc.',400:'No targeted ischemic CNS history.',401:'No five-year cancer history.',402:'No severe-infection assessment.',
940:'No acute hepatic or renal assessment.',945:'No investigational drug history.',946:'No complete drug history, duration, or randomization anchor.',952:'No ventilation or extubation assessment.',953:'No reconciled antifungal allergy history.',957:'No documented prognosis.',
108:'Lesion description supplies no hemodynamic measurements or stability assessment.',109:'No documented septic shock assessment.',111:'No established fistulous cause for the ulcer.',
328:'No personal or family bleeding history.',330:'Urinary RBCs do not establish gastrointestinal bleeding history.',467:'No pre-injury disability history.',475:'Fall from a bike does not establish whether a vehicle was involved.',476:'Fall mechanism does not establish whether another rider was involved.',985:'No device inventory or statement confirming absence of a chest tube.'},
'Partial evidence; key qualifier unresolved': {
25:'Hypertension is explicit; its severity or secondary cause is unspecified.',385:'General consent does not establish ability to take and retain oral medication.',
850:'Prior wheezing is denied; no documented weekly exacerbation count.',890:'Cognitive deficits are demonstrated; exact admission-screening event is not established.',
81:'Fever and inflammatory tests do not determine severity, infectious cause, or screening timing.',115:'A skin lesion is documented; cause is unspecified.',116:'A skin lesion is documented; no burn etiology or specific denial.',
239:'Age and recent amenorrhea are available; menopausal status is not established.',336:'Future willingness does not establish signed consent or authorized proxy consent for an infant.',
366:'Mechanism and abdominal signs available; required laparotomy with primary closure unverified.',367:'Abdominal findings present; open laparotomy with primary closure unverified.',
460:'GCS 6 documented and CT deferred. Required imaging or a qualifying alternative combination is unverified.'},
'Specific person must supply judgment or preference':{
935:'Organism description is available; enrolling physician opinion on mycobacterial culture is absent.',
938:'Willingness to comply does not specifically address blood collection.',939:'General trial consent does not specifically address storage of samples.',
955:'No attributed investigator judgment of unacceptable additional risk.'},
'Missing or ambiguous governing protocol text':{218:'Malformed measurement unit; locate governing source before executing comparison.',919:'Reference to severe CDAD as defined above lacks its definition. Separate clinical confirmation is also missing.',55:'Age is documented but wording does not resolve prematurity history versus present neonatal status.'},
'Multiple subjects; no individual index patient':{493:'Adult group vignette; no individual infant identified.',494:'No single pregnancy or infant identified.',496:'No individual newborn assessment.',497:'No individual newborn infection assessment.',498:'No individual mother or infant. Scope of the requested maternal judgment also needs clarification.'},
'Clinical interpretation from findings':{414:'Symptoms, serology and urine results support clinical review; no definitive SLE diagnosis explicitly recorded.'}}
docs={r['annotation_id']:r['note'] for p in (root.parent,root.parent/'round2') for r in json.loads((p/'blind.json').read_text())}
out=[]
for category,items in groups.items():
 for i,why in items.items():
  r=old[i];out.append(dict(annotation_id=i,criterion=r['criterion'],expert=r['expert'],expert_sentences=r['expert_sentences'],audit_category=category,rationale=why,note=docs[i]))
assert len(out)==len(old)==len(set(r['annotation_id'] for r in out))==49
with (root/'prior_49_audit.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=out[0]);w.writeheader();w.writerows(sorted(out,key=lambda r:r['annotation_id']))
print({k:len(v) for k,v in groups.items()})
