"""Author protocol rules once, record clarifications, and screen normalized FHIR separately."""
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

import bounded_rules
import text_author


FORM = "pocketmd.bounded-rule.v1"
READY = "EXECUTABLE"
PENDING = "AUTHORING_PENDING"
FAILED = "AUTHORING_ERROR"


class ConfigurationError(ValueError):
    """Fixed user-facing diagnostic without provider request or response contents."""


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(obj):
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


def timestamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def required(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + " must be nonempty text")
    return value.strip()


def key_for(study, version, criterion_id):
    return digest([required(s, k) for s, k in ((study, "study"), (version, "version"), (criterion_id, "criterion ID"))])


def trusted_catalog(catalog):
    if not isinstance(catalog, dict) or not isinstance(catalog.get("facts"), dict):
        raise ValueError("Missing catalog mappings")
    expected = bounded_rules.approved_catalog(keys=list(catalog["facts"]))
    if expected != catalog:
        raise ValueError("Catalog differs from the installed mapping release")
    return expected


def atomic_export(path, document):
    """Publish fully written bytes; refuse to replace a different file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        temp = Path(f.name)
        try:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
            try:
                os.link(temp, path)
            except FileExistsError:
                if json.loads(path.read_bytes()) != document:
                    raise ValueError("Destination already contains a different artifact")
        finally:
            temp.unlink(missing_ok=True)


class RuleStore:
    """A study/version/criterion is immutable except for scoped answers and audit revisions."""

    def __init__(self, work):
        self.work = Path(work)
        self.work.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = self.work / "rule-cases.sqlite"
        db_fd = os.open(self.db, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(db_fd)
        with contextlib.closing(self._connect()) as con:
            con.execute("""CREATE TABLE IF NOT EXISTS snapshots
                           (case_key TEXT, revision INTEGER, event TEXT, recorded_at TEXT, document TEXT,
                            PRIMARY KEY(case_key,revision))""")
            con.commit()

    def _connect(self):
        return sqlite3.connect(self.db, timeout=30)

    @contextlib.contextmanager
    def _lock(self, key):
        # OS releases the case lock if this process loses power or a model call is killed.
        # Other criteria can continue during slow model calls.
        with open(self.work / (key + ".lock"), "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    def _latest(self, key):
        with contextlib.closing(self._connect()) as con:
            row = con.execute("SELECT document FROM snapshots WHERE case_key=? ORDER BY revision DESC LIMIT 1",
                              (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def _record(self, case, event):
        key = key_for(case["study"], case["version"], case["id"])
        case["revision"] += 1
        with contextlib.closing(self._connect()) as con, con:
            con.execute("INSERT INTO snapshots VALUES(?,?,?,?,?)",
                        (key, case["revision"], event, timestamp(), canonical(case)))

    def _get(self, key):
        case = self._latest(key)
        if case is None:
            raise ValueError("Unknown study/version/criterion")
        return case

    def show(self, study, version, criterion_id):
        return self._get(key_for(study, version, criterion_id))

    @staticmethod
    def actions(work, owner):
        """List actionable items from the latest revision of each scoped case, without writes."""
        if owner not in {"investigator", "engineering"}:
            raise ValueError("Choose investigator or engineering")
        database = Path(work) / "rule-cases.sqlite"
        if not database.exists():
            return []
        query = """SELECT s.document FROM snapshots s
                   JOIN (SELECT case_key, MAX(revision) AS revision FROM snapshots GROUP BY case_key) latest
                   ON latest.case_key=s.case_key AND latest.revision=s.revision"""
        items = []
        with contextlib.closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as con:
            for (document,) in con.execute(query):
                case = json.loads(document)
                scope = {k: case[k] for k in ("study", "version", "id")}
                if owner == "investigator":
                    items.extend({**scope, "kind": "investigator_question", "question_id": q["id"], "text": q["text"]}
                                 for q in case["questions"])
                else:
                    items.extend({**scope, "kind": "binding_gap", "text": gap} for gap in case["gaps"])
                    if case["status"] in {"VALIDATION_REVIEW", FAILED}:
                        kind = "validation_review" if case["status"] == "VALIDATION_REVIEW" else "provider_error"
                        items.append({**scope, "kind": kind, "text": case["reason"]})
        return sorted(items, key=lambda item: (item["study"], item["version"], item["id"]))

    def history(self, study, version, criterion_id):
        key = key_for(study, version, criterion_id)
        self._get(key)
        with contextlib.closing(self._connect()) as con:
            rows = con.execute("SELECT revision,event,recorded_at,document FROM snapshots WHERE case_key=? "
                               "ORDER BY revision", (key,)).fetchall()
        return [{"revision": n, "event": event, "recorded_at": date, "status": json.loads(doc)["status"]}
                for n, event, date, doc in rows]

    def build(self, study, version, criterion_id, criterion, context, catalog, provider, polarity=None):
        scope = {k: required(v, k) for k, v in (("study", study), ("version", version), ("id", criterion_id))}
        key = key_for(scope["study"], scope["version"], scope["id"])
        sources = {"criterion": required(criterion, "criterion")}
        if context:
            sources["protocol"] = required(context, "protocol context")
        if polarity is not None:
            if polarity not in {"inclusion", "exclusion"}:
                raise ValueError("Polarity must be inclusion or exclusion")
            sources["polarity"] = polarity
        trusted_catalog(catalog)
        with self._lock(key):
            case = self._latest(key)
            if case:
                if case["initial_sources"] != sources or case["catalog"] != catalog:
                    raise ValueError("This version is pinned to different input. Use a new version for an amendment.")
                if case["status"] not in {FAILED, PENDING}:
                    return case
            else:
                case = dict(scope, revision=0, status=PENDING, initial_sources=sources, catalog=catalog,
                            answers=[], question_history=[], questions=[], gaps=[], citations=[], rule=None,
                            reason="Awaiting authoring", last_result=None, expression=None)
                self._record(case, "input_pinned")
            return self._run(case, provider)

    def answer(self, study, version, criterion_id, question, answer, reviewer, provider):
        key = key_for(study, version, criterion_id)
        answer, reviewer = required(answer, "answer"), required(reviewer, "reviewer")
        with self._lock(key):
            case = self._get(key)
            previous = next((a for a in case["answers"] if a["question_id"] == question), None)
            if previous:
                if previous["answer"] != answer or previous["reviewer"] != reviewer:
                    raise ValueError("A different answer or reviewer is already recorded for this question")
                if case["status"] in {FAILED, PENDING}:
                    return self._run(case, provider)
                return case
            open_question = next((q for q in case["questions"] if q["id"] == question), None)
            if not open_question:
                raise ValueError("Question is not open in this study/version/criterion")
            case["answers"].append({"question_id": question, "question": open_question["text"], "answer": answer,
                                    "reviewer": reviewer, "recorded_at": timestamp()})
            case["questions"] = [q for q in case["questions"] if q["id"] != question]
            case.update(status=PENDING, rule=None, expression=None, last_result=None, reason="Answer recorded",
                        citations=[], gaps=[])
            self._record(case, "answer_recorded")
            return self._run(case, provider)

    def retry(self, study, version, criterion_id, provider):
        key = key_for(study, version, criterion_id)
        with self._lock(key):
            case = self._get(key)
            if case["status"] in {FAILED, PENDING, "VALIDATION_REVIEW"}:
                return self._run(case, provider)
            return case

    def _run(self, case, provider):
        sources = dict(case["initial_sources"])
        for answer in case["answers"]:
            key = answer["question_id"]
            sources["question:" + key] = answer["question"]
            sources["answer:" + key] = answer["answer"]
        try:
            result = text_author.propose(sources, case["catalog"], provider)
            status = result["status"]
            if status not in {READY, "INVESTIGATOR_REVIEW", "VALIDATION_REVIEW", "BINDING_REVIEW"}:
                raise ValueError("Authoring returned an unrecognized status")
            # Each open question must receive its own attributed answer. A later draft
            # may not silently abandon a sibling question after a partial response.
            missing_questions = [q["text"] for q in case["questions"] if q["text"] not in result["questions"]]
            if missing_questions:
                status = "INVESTIGATOR_REVIEW"
                result = {**result, "status": status, "expression": None,
                          "questions": [*result["questions"], *missing_questions],
                          "reason": "Previously issued questions still need an attributed answer."}
            rule = None
            if status == READY:
                if result["questions"] or result["gaps"]:
                    raise ValueError("Unresolved obligations in candidate executable")
                rule = self._artifact(case, sources, result)
            if status == "INVESTIGATOR_REVIEW" and not result["questions"]:
                raise ValueError("Missing investigator question")
            questions = self._assign_questions(case, result["questions"])
            case.update(status=status, questions=questions, gaps=result["gaps"], reason=result["reason"],
                        expression=rule["expression"] if rule else None, citations=result["citations"],
                        last_result=result, rule=rule)
            event = "authoring_completed"
        except Exception as error:
            # Third-party errors can contain tokens or raw request/response data.
            reason = ("Supply --model-command or set OPENAI_MODEL and OPENAI_API_KEY, then run retry."
                      if isinstance(error, ConfigurationError)
                      else f"Authoring did not complete ({type(error).__name__}). Check provider availability and retry.")
            case.update(status=FAILED, rule=None, expression=None, last_result=None, citations=[], gaps=[], reason=reason)
            event = "authoring_failed"
        self._record(case, event)
        return case

    @staticmethod
    def _assign_questions(case, texts):
        open_by_text = {q["text"]: q for q in case["questions"]}
        questions = []
        for text in dict.fromkeys(texts):
            text = required(text, "question text")
            q = open_by_text.get(text)
            if q is None:
                q = {"id": "Q" + str(len(case["question_history"]) + 1), "text": text}
                case["question_history"].append(q)
            questions.append(q)
        return questions

    @staticmethod
    def _artifact(case, sources, result):
        catalog = trusted_catalog(case["catalog"])
        bindings = bounded_rules.validate(result["expression"], catalog)
        body = {"format": FORM, "study": case["study"], "version": case["version"], "id": case["id"],
                "expression": result["expression"], "bindings": bindings, "catalog": catalog,
                "sources": sources, "answers": case["answers"], "citations": result["citations"],
                "authoring_review": result, "release": "research"}
        return dict(body, sha256=digest(body))

    def export(self, study, version, criterion_id):
        case = self.show(study, version, criterion_id)
        if case["status"] != READY or not case["rule"]:
            raise ValueError("An executable is unavailable while this case is " + case["status"])
        return case["rule"]


def screen(rule, bundle, patient, encounter, as_of, study=None, version=None, criterion_id=None, expected_sha256=None):
    if not isinstance(rule, dict) or rule.get("format") != FORM:
        raise ValueError("Unsupported rule format")
    if rule.get("sha256") != digest({k:v for k,v in rule.items() if k != "sha256"}):
        raise ValueError("Rule checksum mismatch")
    if expected_sha256 and rule["sha256"] != expected_sha256:
        raise ValueError("Rule checksum differs from the requested release")
    for name, expected in (("study", study), ("version", version), ("id", criterion_id)):
        required(rule.get(name), name)
        if expected is not None and rule[name] != expected:
            raise ValueError("Rule " + name + " differs from the requested scope")
    catalog = trusted_catalog(rule["catalog"])
    if bounded_rules.validate(rule["expression"], catalog) != rule["bindings"]:
        raise ValueError("Rule bindings differ from the pinned mapping")
    review = rule["authoring_review"]
    if (review["status"] != READY or review["expression"] != rule["expression"]
            or review["gaps"] or review["questions"]):
        raise ValueError("Rule is missing a consistent completed authoring review")
    audit = review["audit"]
    def recorded(task, packet):
        return audit["author" if task == "author" else "verification"]
    replay = text_author.propose(rule["sources"], catalog, recorded)
    if (replay["status"] != READY or replay["expression"] != rule["expression"]
            or audit["source_sha256"] != replay["audit"]["source_sha256"]
            or audit["catalog_sha256"] != catalog["sha256"]):
        raise ValueError("Saved source and verification record did not reproduce this rule")
    evaluation = bounded_rules.evaluate(rule["expression"], catalog, bundle, patient, encounter, rule["study"], as_of)
    return {"study": rule["study"], "version": rule["version"], "id": rule["id"], "rule_sha256": rule["sha256"],
            "patient": patient, "encounter": encounter, "as_of": as_of, **evaluation}


def for_display(case):
    return {k: case[k] for k in ("study","version","id","revision","status","questions","gaps","reason","citations",
                                "expression","answers")} | {"rule_sha256": (case["rule"] or {}).get("sha256")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("build","answer","show","retry","export","history","screen"):
        cmd = commands.add_parser(name)
        for flag in ("study","version","id"):
            cmd.add_argument("--" + flag, required=name != "screen")
        if name != "screen":
            cmd.add_argument("--work", required=True, type=Path)
        if name in ("build","answer","retry"):
            options = cmd.add_mutually_exclusive_group()
            options.add_argument("--model-command", help="Trusted author/verify adapter command")
            options.add_argument("--model", help="OpenAI Responses model (or set OPENAI_MODEL)")
        if name == "build":
            cmd.add_argument("--criterion", required=True)
            cmd.add_argument("--polarity", choices=("inclusion", "exclusion"), help="Protocol section governing this clause")
            context = cmd.add_mutually_exclusive_group()
            context.add_argument("--context")
            context.add_argument("--context-file", type=Path)
            cmd.add_argument("--facts", nargs="+", help="Restrict the approved catalog to these fact keys")
        elif name == "answer":
            for arg in ("question","answer","reviewer"):
                cmd.add_argument("--" + arg, required=True)
        elif name == "export":
            cmd.add_argument("--out", required=True, type=Path)
        elif name == "screen":
            cmd.add_argument("--rule", required=True, type=Path)
            cmd.add_argument("--bundle", required=True, type=Path)
            cmd.add_argument("--expected-sha256", help="Pin screening to a known exported release")
            for arg in ("patient","encounter","as-of"):
                cmd.add_argument("--" + arg, required=True)
    actions = commands.add_parser("actions", help="List only current work for an owner across all study versions")
    actions.add_argument("--work", required=True, type=Path)
    actions.add_argument("--owner", required=True, choices=("investigator", "engineering"))
    args = parser.parse_args(argv)
    try:
        if args.command == "actions":
            result = RuleStore.actions(args.work, args.owner)
        elif args.command == "screen":
            result = screen(json.loads(args.rule.read_bytes()), json.loads(args.bundle.read_bytes()), args.patient,
                            args.encounter, args.as_of, args.study, args.version, args.id, args.expected_sha256)
        else:
            store = RuleStore(args.work)
            scope = (args.study,args.version,args.id)
            if args.command in ("build","answer","retry"):
                # Build the provider lazily so identical retries never require credentials.
                cached = None
                command = args.model_command if args.model_command is not None else (
                    None if args.model else os.environ.get("POCKETMD_MODEL_COMMAND"))
                model = args.model or os.environ.get("OPENAI_MODEL")
                def provider(task, packet):
                    nonlocal cached
                    if cached is None:
                        if not command and (not model or not os.environ.get("OPENAI_API_KEY")):
                            raise ConfigurationError()
                        cached = text_author.make_provider(model, command)
                    return cached(task, packet)
                provider.info = {"transport": "command"} if command else {"transport":"openai_responses", "model":model}
                if args.command == "build":
                    context = args.context_file.read_text() if args.context_file else args.context
                    case = store.build(*scope, args.criterion, context, bounded_rules.approved_catalog(keys=args.facts),
                                       provider, polarity=args.polarity)
                elif args.command == "answer":
                    case = store.answer(*scope, args.question, args.answer, args.reviewer, provider)
                else:
                    case = store.retry(*scope, provider)
                result = for_display(case)
            elif args.command == "show":
                result = for_display(store.show(*scope))
            elif args.command == "history":
                result = store.history(*scope)
            else:
                rule = store.export(*scope)
                atomic_export(args.out, rule)
                result = {"path":str(args.out), "sha256":rule["sha256"]}
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1 if isinstance(result, dict) and result.get("status") == FAILED else 0
    except (ValueError, TypeError, OSError, sqlite3.Error, KeyError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
