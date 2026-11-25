"""Synthetic native FHIR binding, integrity and boundary tests. Run as a script or unittest."""
from copy import deepcopy
from pathlib import Path
import json
import unittest

import entry_adapter as entry
import normalized as n

def run_checks(rules):
    cases=[]
    def run(name,packet,expected):
        derived=entry.derive(rules, packet["bundle"],packet["context"])
        for rulekey,fkey,want in expected:
            rule=rules.get(rulekey) or rules["106S01-"+rulekey]
            result=derived.get(n.contract(rule["facts"][fkey]))
            got=(result[1] or result[0]) if result else "ABSENT"
            assert got==want,(name,fkey,want,got)
            if result and not result[1]:assert result[2] and all('/_history/' in r for r in result[2])
            cases.append(dict(case=name,criterion=rulekey,fact=fkey,expected=want,actual=got))
    def get(p,t,id=None):
        return next(e["resource"] for e in p["bundle"]["entry"] if e["resource"]["resourceType"]==t and (id is None or e["resource"]["id"]==id))
    age=lambda v:("I01","age_at_prescreen",v)
    kg=lambda v:("I01","prescreen_weight",v)
    path=lambda v:("I17","index_histology",v)
    p=entry.native_example(rules)
    run('source-confirmed birthday and 30 kg boundary',p,[age(18),kg(30),path("OSTEOSARCOMA")])
    p=entry.native_example(rules,birth="2008-05-02",signer="legal_representative")
    run('birthday tomorrow with guardian consent',p,[age(17),kg(30)])
    p=entry.native_example(rules,birth="2014-05-01",signer="legal_representative")
    run('minor exactly 12',p,[age(12)])
    p=entry.native_example(rules,birth="2014-05-01")
    run('minor self-signature alone',p,[age("MISSING_DATA"),kg("MISSING_DATA")])
    p=entry.native_example(rules,signing_time="2026-05-01T02:00:00Z",birth="2008-04-30")
    get(p,"Observation")["effectiveDateTime"]="2026-04-30T09:00:00-07:00"
    run('local calendar across UTC midnight',p,[age(18),kg(30)])
    p=entry.native_example(rules)
    p["context"]["site_zone"]="Unavailable/Zone"
    run('unsupported site calendar',p,[age("MISSING_DATA"),kg("MISSING_DATA")])
    p=entry.native_example(rules);get(p,"Observation")["effectiveDateTime"]="2026-04-30T09:00:00-07:00"
    run('different measurement day',p,[age(18),kg("ABSENT")])
    p=entry.native_example(rules);get(p,"Observation")["effectiveDateTime"]="2026-05-01"
    run('full past local clinical date',p,[kg(30)])
    p=entry.native_example(rules);get(p,"Observation")["effectiveDateTime"]="2026-05"
    run('month precision',p,[kg("MISSING_DATA")])
    p=entry.native_example(rules);get(p,"Observation")["code"]={"coding":[{"system":"urn:local","code":"29463-7","display":"Body Weight"}]}
    run('unmapped hospital code',p,[kg("ABSENT")])
    p=entry.native_example(rules);get(p,"Observation")["subject"]={"reference":"Patient/other"}
    run('wrong patient has the measurement',p,[kg("ABSENT")])
    p=entry.native_example(rules);get(p,"Observation")["encounter"]={"reference":"Encounter/other"}
    run('weight belongs to another visit',p,[kg("ABSENT")])
    for desc,mutate in [
        ('wrong-scope weight document',lambda p:get(p,"DocumentReference","weight-report").update(subject={"reference":"Patient/other"})),
        ('unversioned weight source',lambda p:get(p,"Observation").update(derivedFrom=[{"reference":"DocumentReference/weight-report"}])),
        ('untrusted performer',lambda p:get(p,"Observation").update(performer=[{"reference":"Organization/other"}])),
        ('non-UCUM kilograms',lambda p:get(p,"Observation")['valueQuantity'].update(system="urn:local")),
        ('comparator instead of measured weight',lambda p:get(p,"Observation")['valueQuantity'].update(comparator=">")),
        ('future issuance',lambda p:get(p,"Observation").update(issued="2027-01-01T00:00:00Z")),
    ]:
        p=entry.native_example(rules);mutate(p);run(desc,p,[age(18),kg("MISSING_DATA")])
    p=entry.native_example(rules);second=deepcopy(get(p,"Observation"));second['id']='weight2';second['valueQuantity']['value']=28
    p["bundle"]["entry"].append({"resource":second})
    run('contradictory same-day weights',p,[kg("MISSING_DATA")])
    for desc,mutate in [
        ('no signature provenance',lambda p:p["bundle"].update(entry=[e for e in p["bundle"]["entry"] if e["resource"]["resourceType"]!="Provenance"])),
        ('wrong signature public key',lambda p:p["context"]["prescreen_signers"]["Patient/demo"].update(public_key="AAAA")),
        ('altered signed document',lambda p:get(p,"DocumentReference","prescreen")['content'][0]['attachment'].update(data="bW9kaWZpZWQ=")),
        ('wrong consent source subject',lambda p:get(p,"DocumentReference","prescreen").update(subject={"reference":"Patient/other"})),
        ('imprecise birthdate',lambda p:get(p,"Patient").update(birthDate="2008-05")),
    ]:
        p=entry.native_example(rules);mutate(p);run(desc,p,[age("MISSING_DATA"),kg("MISSING_DATA")])
    p=entry.native_example(rules);p["context"]["prescreen_signers"]["Patient/demo"]["through"]="2025-12-31T00:00:00Z"
    run('signer registration expired',p,[age("MISSING_DATA")])
    p=entry.native_example(rules);get(p,"Consent")["category"]=[{"coding":[{"system":entry.FORM,"code":"formal-main-icf"}]}]
    run('main consent cannot replace prescreen form',p,[age("ABSENT"),kg("ABSENT")])
    for desc,mutate,want in [
        ('local-only histology',lambda p:get(p,"Condition").update(code={"coding":[{"system":"urn:local","code":"9180/3"}]}),"ABSENT"),
        ('unlinked histology',lambda p:get(p,"Condition").update(evidence=[]),"MISSING_DATA"),
        ('wrong cancer specimen patient',lambda p:get(p,"Specimen").update(subject={"reference":"Patient/other"}),"MISSING_DATA"),
        ('preliminary report',lambda p:get(p,"DiagnosticReport").update(status="preliminary"),"MISSING_DATA"),
        ('ambiguous standardized codes',lambda p:get(p,"Condition")["code"]["coding"].append({"system":entry.ICDO,"code":"8890/3"}),"MISSING_DATA"),
        ('conflicting coding in pathology report',lambda p:get(p,"DiagnosticReport")["conclusionCode"][0]["coding"].append({"system":entry.ICDO,"code":"8890/3"}),"MISSING_DATA"),
        ('pathology disagrees with condition',lambda p:get(p,"DiagnosticReport").update(conclusionCode=[{"coding":[{"system":entry.ICDO,"code":"8890/3"}]}]),"MISSING_DATA"),
    ]:
        p=entry.native_example(rules);mutate(p);run(desc,p,[path(want)])
    p=entry.native_example(rules)
    get(p,"Observation").update(effectiveDateTime="2026-05-01",issued="2026-04-30T16:00:00Z")
    run('calendar measurement is later than issuing record',p,[kg("MISSING_DATA")])
    p=entry.native_example(rules); get(p,"Encounter").update(status="entered-in-error")
    run('encounter assigned in error',p,[age("MISSING_DATA"),kg("MISSING_DATA")])
    p=entry.native_example(rules,birth="2014-05-01",signer="legal_representative")
    get(p,"RelatedPerson").update(patient={"reference":"Patient/other"})
    run('representative linked to another patient',p,[age("MISSING_DATA"),kg("MISSING_DATA")])
    p=entry.native_example(rules)
    get(p,"Provenance")["signature"][0]["when"]="2026-05-01T08:00:00-07:00"
    run('changed signature date',p,[age("MISSING_DATA"),kg("MISSING_DATA")])
    def screen(name,p,want):
        snap=n.Snapshot(p["bundle"],p["context"])
        snap.native.update(entry.derive(rules,p["bundle"],p["context"]))
        rule=rules.get("I01") or rules["106S01-I01"]
        got=n.evaluate(rule,snap)["state"]
        assert got==want,(name,got,want)
        cases.append(dict(case=name,criterion="I01",fact="full rule",expected=want,actual=got))
    screen('adult native chart fully evaluates',entry.native_example(rules),'MET')
    screen('adult at 29.99 kg fails independent of site adolescent branch',entry.native_example(rules,weight=29.99),'NOT_MET')
    screen('qualifying adolescent needs independent operational evidence',
           entry.native_example(rules,birth="2011-05-01",signer="legal_representative"),'STUDY_ACTION')
    screen('below twelve resolves with measured weight and signed representative consent',entry.native_example(rules,birth="2014-05-02",signer="legal_representative"),'NOT_MET')
    p=n.make_packet(rules,{})
    run('no native evidence provided',p,[age("ABSENT"),kg("ABSENT"),path("ABSENT")])
    return cases

def rules_for_tests():
    root=Path(__file__).resolve().parent
    for p in [root/'rules.json',root/'sotio_rules.json',root.parent/'authoring/entry/rules.json']:
        if p.exists():
            r=json.loads(p.read_text());r=r.get("rules",r)
            if isinstance(r,dict) and ("I01" in r or "106S01-I01" in r):return r
    raise FileNotFoundError("Provide SOTIO rule definitions to run_checks(rules).")

class NativeEntryTests(unittest.TestCase):
    def test_native(self):
        self.assertTrue(run_checks(rules_for_tests()))

if __name__=='__main__':
    print(json.dumps(run_checks(rules_for_tests()),indent=2))
