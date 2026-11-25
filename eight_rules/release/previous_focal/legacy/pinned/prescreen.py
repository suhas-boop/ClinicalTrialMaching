"""Evaluate a normalized prescreen tissue-assay contract on a single study attempt."""
from decimal import Decimal
from zoneinfo import ZoneInfo

from evidence import (boolean_answer, codes, decision, instant, meets_inclusive_minimum,
                      only_value, ref, references, require, single)

PHASE_SYSTEM = 'urn:pocketmd:demo:prescreen:v1'
STUDY_ID = 'urn:pocketmd:demo:screening-study'
FINAL = {'final', 'amended', 'corrected'}


def phase(visit):
    return {code for item in visit.get('type', []) for code in codes(item, PHASE_SYSTEM)}


def is_prescreening(visit):
    return 'prescreening' in phase(visit)


class PrescreenEvidence:
    def __init__(self, chart, spec):
        self.chart = chart
        self.spec = spec
        self.system = spec['system']
        self.used = set(chart.evidence)

    def resolve(self, reference, kind):
        logical, _, version = reference.partition('/_history/')
        r = self.chart.resources.get(logical)
        require(version and r and r['resourceType'] == kind and ref(r) == reference,
                'Verify the exact ' + kind + ' version.')
        self.used.add(reference)
        return r

    def setup(self):
        visit = self.chart.encounter
        self.formal = phase(visit) == {'formal-screening-assessments'}
        require(self.formal or phase(visit) == {'prescreening'},
                'Identify the prescreening or formal screening assessment encounter.')
        link = single(references(visit.get('episodeOfCare', [])), 'Identify the screening attempt.')
        episode = self.resolve(link, 'EpisodeOfCare')
        typed = any(codes(c, self.system) == {'trial-screening-attempt'} for c in episode.get('type', []))
        study = [i['value'] for i in episode.get('identifier', []) if i.get('system') == STUDY_ID]
        require(episode['patient']['reference'] == self.chart.person and typed and study == [self.chart.study]
                and episode.get('status') in ('active', 'finished'), 'Verify the study, patient and screening attempt.')
        self.index = single([d['condition']['reference'] for d in episode.get('diagnosis', [])],
                            'Identify the index tumor for this screening attempt.')
        tumor = self.resolve(self.index, 'Condition')
        require(tumor['subject']['reference'] == self.chart.person, 'Verify the patient on the index tumor.')
        visits = [v for v in self.chart.resources.values()
                  if v['resourceType'] == 'Encounter' and v.get('subject', {}).get('reference') == self.chart.person
                  and references(v.get('episodeOfCare', [])) == [link] and v.get('status') in ('in-progress','finished')]
        for v in visits:
            ids = [i['value'] for i in v.get('identifier', []) if i.get('system') == STUDY_ID]
            require(ids == [self.chart.study], 'Resolve the study identity of the linked encounter.')
        self.pre = single([v for v in visits if phase(v) == {'prescreening'}],
                          'Identify one prescreening encounter for this attempt.')
        formal_visits = [v for v in visits if phase(v) == {'formal-screening-assessments'}
                        and instant(v['period']['start']) <= self.chart.cutoff]
        if self.formal:
            require(len(formal_visits) == 1, 'Resolve the first formal screening assessment for this attempt.')
        else:
            require(not formal_visits, 'Use the formal screening assessment encounter for this attempt.')
        self.used.add(ref(self.pre))
        self.pre_id = 'Encounter/' + self.pre['id']
        self.pre_refs = {self.pre_id, ref(self.pre)}

    def items(self, kind, visits):
        return [r for r in self.chart.resources.values()
                if r['resourceType'] == kind and r.get('subject', {}).get('reference') == self.chart.person
                and r.get('encounter', {}).get('reference') in visits]

    def event(self, name, earliest=None, latest=None):
        test, doc_type, field = self.spec['events'][name]
        visits = set(self.pre_refs)
        if name == 'main_signature':
            visits.update((self.chart.visit, ref(self.chart.encounter)))
        values = set()
        for r in self.items('Observation', visits):
            labels = codes(r['code'], self.system)
            if test not in labels or r.get('status') in ('entered-in-error','cancelled'):
                continue
            released = instant(r['issued'])
            if released > self.chart.cutoff:
                continue
            t = instant(r['effectiveDateTime'])
            if (earliest is not None and t < earliest) or (latest is not None and t > latest):
                continue
            require(labels == {test} and r.get('status') in FINAL and t <= released,
                    'Verify the final source for ' + name + '.')
            doc_ref = single(references(r.get('derivedFrom', [])), 'Verify the source for ' + name + '.')
            doc = self.resolve(doc_ref, 'DocumentReference')
            require(doc['subject']['reference'] == self.chart.person and doc.get('status') == 'current'
                    and doc.get('docStatus') in ('final','amended') and codes(doc['type'], self.system) == {doc_type}
                    and r['encounter']['reference'] in references(doc.get('context', {}).get('encounter', []))
                    and instant(doc['date']) <= self.chart.cutoff, 'Verify the original document for ' + name + '.')
            if name in ('archive_available','fresh_feasibility'):
                require(references(r.get('focus', [])) == [self.index], 'Verify the index tumor for the tissue review.')
            value = only_value(r, field)
            if field == 'valueDateTime':
                value = instant(value)
                require(value == t, 'Verify the actual consent signature time.')
            elif field == 'valueCodeableConcept':
                value = single(sorted(codes(value, self.system)), 'Verify biopsy feasibility.')
            else:
                require(type(value) is bool, 'Verify the tissue availability assessment.')
            values.add(value)
            self.used.add(ref(r))
        require(len(values) <= 1, 'Reconcile conflicting records for ' + name + '.')
        return next(iter(values), None)

    def willingness(self, earliest, latest):
        values = set()
        for r in self.items('QuestionnaireResponse', self.pre_refs):
            if r.get('questionnaire') != self.spec['questionnaire'] or r.get('status') == 'entered-in-error':
                continue
            if not earliest <= instant(r['authored']) <= latest:
                continue
            require(r.get('status') in ('completed','amended') and r.get('source', {}).get('reference') == self.chart.person,
                    'Verify the patient response and respondent for this screening attempt.')
            answers = [i for i in r.get('item', []) if i.get('linkId') == self.spec['willingness_item']]
            item = single(answers, 'Verify the patient’s answer about fresh biopsy.')
            value = boolean_answer(item)
            self.used.add(ref(r))
            values.add(value)
        require(len(values) <= 1, 'Reconcile the patient’s recorded biopsy responses.')
        return next(iter(values), None)

    def central_report(self):
        central = []
        other = False
        for report in self.items('DiagnosticReport', self.pre_refs):
            labels = codes(report['code'], self.system)
            if self.spec['assay'] not in labels or report.get('status') in ('entered-in-error','cancelled'):
                continue
            if report.get('issued') and instant(report['issued']) > self.chart.cutoff:
                continue
            other = True
            require(labels == {self.spec['assay']}, 'Verify the trial assay identity.')
            if report.get('status') not in FINAL:
                continue
            actor = single(references(report.get('performer', [])), 'Verify the laboratory on the final trial report.')
            lab = self.resolve(actor, 'Organization')
            target = self.spec['laboratory_identifier']
            ids = [i['value'] for i in lab.get('identifier', []) if i.get('system') == target['system']]
            if lab.get('active') is True and ids == [target['value']]:
                central.append((report, actor))
        if central:
            report, actor = single(central, 'Reconcile the governing final central-laboratory report for this attempt.')
            self.used.add(ref(report))
            return report, actor
        require(not other, 'Obtain the final report from the study-designated central laboratory.')
        return None, None

    def has_open_lab_work(self):
        for order in self.items('ServiceRequest', self.pre_refs):
            if codes(order.get('code', {}), self.system) == {self.spec['assay']} and order.get('intent') == 'order':
                if (order.get('status') in ('active','completed','on-hold') and instant(order['authoredOn']) <= self.chart.cutoff
                        and references(order.get('reasonReference', [])) == [self.index]):
                    self.used.add(ref(order))
                    return True
        return False

    def tissue_route(self, rule, specimen, signed, ordered):
        label = single(sorted(codes(specimen['type'], self.system)), 'Verify the tumor tissue source.')
        method = codes(specimen['collection']['method'], self.system)
        adequacy = {v for c in specimen.get('condition', []) for v in codes(c, self.system)}
        require(specimen.get('status') in ('available','unavailable') and len(method) == 1
                and method.issubset(self.spec['collection_methods']) and adequacy == {'adequate-for-ihc'},
                'Obtain an adequate non-aspirate tumor biopsy for the study assay.')
        containers = specimen.get('container', [])
        forms = [codes(c.get('type', {}), self.system) for c in containers]
        require(forms and all(len(f) == 1 and f.issubset(self.spec['submitted_forms']) for f in forms),
                'Verify the submitted FFPE block or unstained slides from FFPE tissue.')
        if label == 'freshly-obtained-tumor-biopsy':
            return 'fresh'
        require(label == 'archival-tumor-biopsy', 'Verify whether this is fresh or archival tumor tissue.')
        reason = self.event('fresh_feasibility', earliest=signed, latest=ordered)
        if reason in rule['archival_fallback']:
            return 'archival'
        if reason == 'safe-and-accessible':
            return 'archive-scope'
        return 'needs-assessment'

    def assay(self, report, actor):
        order = self.resolve(single(references(report.get('basedOn', [])), 'Identify the trial assay order.'), 'ServiceRequest')
        sample_ref = single(references(report.get('specimen', [])), 'Identify the tested specimen.')
        specimen = self.resolve(sample_ref, 'Specimen')
        require(specimen['subject']['reference'] == self.chart.person
                and order['subject']['reference'] == self.chart.person and order.get('encounter', {}).get('reference') in self.pre_refs
                and order.get('status') in ('active','completed') and order.get('intent') == 'order'
                and codes(order['code'], self.system) == {self.spec['assay']}
                and references(order.get('reasonReference', [])) == [self.index] and references(order.get('specimen', [])) == [sample_ref],
                'Verify the study order, patient, index tumor and tested specimen together.')
        results = [self.resolve(link,'Observation') for link in references(report.get('result', []))]
        matches = [r for r in results if self.spec['result'] in codes(r['code'], self.system)]
        r = single(matches, 'Obtain the percent of cells with LRRC15 staining at intensity 1+ or greater on this specimen.')
        require(codes(r['code'], self.system) == {self.spec['result']} and codes(r['method'], self.system) == {self.spec['assay']}
                and r.get('status') in FINAL and r['subject']['reference'] == self.chart.person
                and r.get('encounter', {}).get('reference') in self.pre_refs and r.get('specimen', {}).get('reference') == sample_ref
                and references(r.get('performer', [])) == [actor], 'Verify the same patient, specimen, central lab and IHC method.')
        q = only_value(r,'valueQuantity')
        require(q.get('system') == self.spec['unit_system'] and q.get('code') == self.spec['unit']
                and type(q.get('value')) in (int,float), 'Verify a numeric result in UCUM percent.')
        pct = Decimal(str(q['value']))
        op = q.get('comparator')
        require(pct.is_finite() and 0 <= pct <= 100 and op in (None,'<','<=','>','>=')
                and (pct,op) not in ((0,'<'),(100,'>')), 'Verify the percentage and its comparator.')
        collected = instant(specimen['collection']['collectedDateTime'])
        tested = instant(r['effectiveDateTime'])
        released = instant(report['issued'])
        ordered = instant(order['authoredOn'])
        require(ordered <= tested and collected <= tested <= instant(r['issued']) <= released <= self.chart.cutoff,
                'Verify collection, test and central report release times.')
        return specimen, pct, op, collected, ordered, released


def evaluate_tissue_assay(chart, rule, spec, site_zone):
    evidence = PrescreenEvidence(chart, spec)
    def outcome(state, reason):
        return decision(state, reason, evidence.used)
    try:
        evidence.setup()
        report, actor = evidence.central_report()
        presigned = evidence.event('prescreen_signature')
        require(presigned is not None, 'Obtain the actual signed prescreening consent and its time.')
        main = evidence.event('main_signature')
        if evidence.formal:
            require(main is not None and main <= chart.start, 'Verify actual main consent at or before the formal screening assessment.')
        if main is not None:
            require(presigned <= main, 'Verify the order of the two consent signatures.')
        zone = ZoneInfo(site_zone) if site_zone else chart.cutoff.tzinfo
        end_day = (main or chart.cutoff).astimezone(zone).date()
        elapsed_days = (end_day - presigned.astimezone(zone).date()).days
        require(0 <= elapsed_days <= rule['prescreen_days'], 'Verify the consent dates and the current prescreening window.')
        if not report:
            if evidence.has_open_lab_work():
                return outcome('MISSING_DATA','A trial assay order already exists. Check collection and obtain the final central report.')
            through = main or chart.cutoff
            require(presigned <= through, 'Verify the prescreen consent time for this attempt.')
            archive = evidence.event('archive_available', earliest=presigned, latest=through)
            if archive is True:
                return outcome('MISSING_DATA','Locate the central IHC result and verify the archived specimen route.')
            willing = evidence.willingness(presigned, through)
            if archive is False and willing is False:
                return outcome('NOT_MET','Adequate archival tissue is unavailable and the patient declined fresh biopsy.')
            feasibility = evidence.event('fresh_feasibility', earliest=presigned, latest=through)
            if feasibility in rule['archival_fallback']:
                return outcome('INVESTIGATOR_ACTIONS','Fresh biopsy is documented as unsafe or inaccessible. Review archival tissue options with the clinical team.')
            if archive is False and willing is None and not evidence.formal and main is None and evidence.pre['status'] == 'in-progress':
                return outcome('PATIENT_SURVEY','Ask whether the patient is willing to undergo a fresh tumor biopsy.')
            if willing is True:
                return outcome('MISSING_DATA','Fresh biopsy willingness is documented. Obtain the prescribed central assay result.')
            if archive is False:
                return outcome('MISSING_DATA','Reconcile the prescreen biopsy history and central report before proceeding.')
            return outcome('MISSING_DATA','Establish whether adequate archival tissue is available.')

        specimen, pct, op, collected, ordered, released = evidence.assay(report, actor)
        route = evidence.tissue_route(rule, specimen, presigned, ordered)
        require(presigned <= ordered, 'Verify the prescreening consent signature before the assay order.')
        if route == 'fresh':
            require(presigned <= collected, 'Verify that fresh tissue collection followed prescreening consent.')
        if evidence.formal:
            require(released < chart.start, 'Obtain a central result available before the first formal screening assessment.')
        require(released.astimezone(zone).date() <= end_day, 'Verify release of the central report within the actual prescreen window.')

        if route == 'needs-assessment':
            return outcome('INVESTIGATOR_ACTIONS','Document whether fresh biopsy is infeasible because of safety or tumor inaccessibility.')
        if route == 'archive-scope':
            result = outcome('AUTHORING_HOLD','Confirm whether archival tissue alone is acceptable when fresh biopsy is feasible.')
            result['question_id'] = rule['archival_scope_question']
            return result

        minimum = Decimal(str(rule['minimum_percent']))
        meets_minimum = meets_inclusive_minimum(op, pct, minimum)
        if meets_minimum is None:
            return outcome('MISSING_DATA','Obtain a central result that resolves the minimum percent at the specified intensity.')
        state = 'MET' if meets_minimum else 'NOT_MET'
        result = outcome(state, f'Central IHC on qualifying {route} tumor tissue. '
                         f'Cells at intensity ≥1+: {op or ""}{pct}%, protocol minimum {minimum}%.')
        result['qualified_report'] = ref(report)
        result['phase'] = 'screening' if evidence.formal else 'prescreening'
        return result
    except (KeyError, ValueError, TypeError, AttributeError, ArithmeticError) as error:
        return outcome('MISSING_DATA', 'Evidence could not be verified: ' + str(error))
