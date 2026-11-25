"""Amendment-scoped question intake and attributed reviewer feedback."""
import datetime
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path


_RUNTIME = Path(__file__).resolve().parent / "runtime"
_ID_FIELDS = {"id", "question_id", "existing_question_id", "registered_id", "registry_id", "intended_owner"}
# The frozen I18 engineering comparison established identity for Q1 only, including its
# alternatives/example/citations. A new wording or changed branch needs separate review.
_VERIFIED_ALIASES = {
    ("106S01", "106S01-I18", "6e80a01373fd98d53a3ca3c15d720e3d9bc32e98342db32a54284349b7f6f22a",
     "e62019c9b0161ec8b6e06adebf5b9c293aacb1c44ceecb0c9fdeafc8b0f0cef2"): "SOTIO-PROGRESSION"
}
_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_questions (
 id TEXT PRIMARY KEY, study TEXT NOT NULL, criterion_id TEXT NOT NULL,
 protocol_sha256 TEXT NOT NULL, fingerprint TEXT NOT NULL, registered_id TEXT,
 question TEXT NOT NULL, details TEXT NOT NULL, possible_duplicate_of TEXT,
 UNIQUE(study, criterion_id, protocol_sha256, fingerprint)
);
CREATE INDEX IF NOT EXISTS review_scope ON review_questions(study,criterion_id,protocol_sha256);
CREATE TABLE IF NOT EXISTS reviewer_answers (
 question_id TEXT PRIMARY KEY REFERENCES review_questions(id), answer TEXT NOT NULL,
 authority TEXT NOT NULL, decision_date TEXT NOT NULL, source_reference TEXT NOT NULL
);
"""
_SELECT = """SELECT q.*, a.answer, a.authority, a.decision_date, a.source_reference
             FROM review_questions q LEFT JOIN reviewer_answers a ON a.question_id=q.id"""
_SCOPE = "q.study=? AND q.criterion_id=? AND q.protocol_sha256=?"


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Supply a nonempty {label}.")
    return value.strip()


def _scope(packet):
    study, criterion, digest = (_text(packet.get(k), k) for k in ("study", "criterion_id", "protocol_sha256"))
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("Supply a lowercase SHA-256 digest for the protocol version.")
    return study, criterion, digest


def _normalize(value):
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    return value


def _hash(value):
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()


def _row(raw):
    result = dict(raw)
    result["details"] = json.loads(result["details"])
    result["question_id"] = result["id"]
    result["status"] = "ANSWERED" if result["answer"] is not None else "OPEN"
    return result


class ReviewQueue:
    """Durable local registry. Model-local IDs such as Q1 are never persistence keys."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.studies = json.loads((_RUNTIME / "inventory.json").read_text())["studies"]
        self.registry = json.loads((_RUNTIME / "coordinator_questions.json").read_text())
        with closing(self._connect()) as conn:
            conn.executescript(_SCHEMA)

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _templates(self, scope):
        study, criterion, sha = scope
        if self.studies.get(study, {}).get("protocol_sha256") != sha:
            return {}
        return {q["id"]: q for q in self.registry.get(study, []) if q["criterion"] == criterion}

    def _match(self, question, scope, templates, fingerprint):
        alias = _VERIFIED_ALIASES.get((*scope, fingerprint))
        if alias in templates:
            return alias, None
        hint = (question.get("existing_question_id") or question.get("registered_id")
                or question.get("registry_id") or question.get("question_id") or question.get("id"))
        possible = hint if isinstance(hint, str) and hint in templates else None
        for key, item in templates.items():
            if _normalize(question["question"]) != _normalize(item["question"]):
                continue
            # Protect qualifiers beyond the words of the question. Newly supplied answers,
            # examples, branches or nonidentical location need an independent match.
            context = {k: v for k, v in question.items() if k not in _ID_FIELDS and k != "question"}
            if all(k in item and _normalize(v) == _normalize(item[k]) for k, v in context.items()):
                if _normalize(question.get("when")) == _normalize(item.get("when")):
                    return key, None
            possible = key
        return None, possible

    def register(self, packet, draft):
        scope = _scope(packet)
        if draft.get("criterion_id") != scope[1] or draft.get("protocol_sha256") != scope[2]:
            raise ValueError("Model response belongs to a different criterion or protocol.")
        questions = draft.get("clinical_questions")
        if not isinstance(questions, list):
            raise ValueError("clinical_questions must be a list.")
        templates = self._templates(scope)
        results = []
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            for question in questions:
                if not isinstance(question, dict):
                    raise ValueError("Each proposed question must be an object.")
                wording = _text(question.get("question"), "question")
                material = {k: v for k, v in question.items() if k not in _ID_FIELDS}
                fingerprint = _hash(_normalize(material))
                native, possible = self._match(question, scope, templates, fingerprint)
                stable_id = native or "PMD-" + _hash([*scope, fingerprint])[:24]
                if native is None and possible is None:
                    # A proposed link to an existing dynamic ID is a hint, not an authorization
                    # to reuse its answer for changed wording or qualifiers.
                    hint = question.get("existing_question_id")
                    if isinstance(hint, str) and hint != stable_id:
                        match = conn.execute(_SELECT + " WHERE " + _SCOPE + " AND q.id=?", (*scope, hint)).fetchone()
                        if match is not None:
                            possible = match["id"]
                existing = conn.execute(_SELECT + " WHERE q.id=?", (stable_id,)).fetchone()
                if existing is not None and tuple(existing[k] for k in ("study", "criterion_id", "protocol_sha256")) != scope:
                    raise ValueError("Registered question ID collides with a different protocol scope.")
                if existing is None:
                    if native:
                        wording = templates[native]["question"]
                    conn.execute("""INSERT INTO review_questions
                        (id,study,criterion_id,protocol_sha256,fingerprint,registered_id,question,details,possible_duplicate_of)
                        VALUES (?,?,?,?,?,?,?,?,?)""",
                        (stable_id, *scope, fingerprint, native, wording, json.dumps(question, ensure_ascii=False), possible))
                result = _row(conn.execute(_SELECT + " WHERE q.id=?", (stable_id,)).fetchone())
                result["is_new"] = existing is None
                results.append(result)
        return results

    def pending(self):
        with closing(self._connect()) as conn:
            return [_row(r) for r in conn.execute(_SELECT + " WHERE a.answer IS NULL ORDER BY q.rowid")]

    def open_for(self, packet):
        with closing(self._connect()) as conn:
            return [_row(r) for r in conn.execute(_SELECT + " WHERE " + _SCOPE + " AND a.answer IS NULL ORDER BY q.rowid", _scope(packet))]

    def answers(self, packet):
        with closing(self._connect()) as conn:
            rows = conn.execute(_SELECT + " WHERE " + _SCOPE + " AND a.answer IS NOT NULL ORDER BY q.rowid", _scope(packet))
            return [{**{k: r[k] for k in ("study", "criterion_id", "protocol_sha256", "question", "answer",
                                          "authority", "decision_date", "source_reference")},
                     "question_id": r["id"]} for r in rows]

    def answer(self, question_id, answer, authority, date, source):
        values = tuple(_text(v, k) for k, v in zip(("answer", "authority", "decision date", "source reference"),
                                                   (answer, authority, date, source)))
        if datetime.date.fromisoformat(values[2]).isoformat() != values[2]:
            raise ValueError("Use a decision date in YYYY-MM-DD format.")
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            record = conn.execute(_SELECT + " WHERE q.id=?", (question_id,)).fetchone()
            if record is None:
                raise ValueError("Unknown reviewer question ID.")
            if record["answer"] is None:
                conn.execute("INSERT INTO reviewer_answers VALUES(?,?,?,?,?)", (question_id, *values))
            elif tuple(record[k] for k in ("answer", "authority", "decision_date", "source_reference")) != values:
                raise ValueError("Conflicting reviewer response. The existing attributed answer was preserved.")
            return _row(conn.execute(_SELECT + " WHERE q.id=?", (question_id,)).fetchone())
