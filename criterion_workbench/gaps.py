"""Persistent engineering work queue for unresolved evidence contracts."""
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from compiler import digest


_SCOPE_FIELDS = ("study", "criterion_id", "protocol_sha256")
_FILTER = "study=? AND criterion_id=? AND protocol_sha256=?"
_GAP_STATES = {"BINDING_REVIEW", "PROTOCOL_AND_BINDING_REVIEW"}
# IDs and candidate sources describe a proposal. Additional fields such as a unit,
# timing restriction, performer, episode qualifier, or evidence type define its contract.
_PROPOSAL_FIELDS = {"id", "status", "catalog_key", "proposed_source"}
_SCHEMA = """
CREATE TABLE IF NOT EXISTS gap_runs (
 ticket INTEGER PRIMARY KEY AUTOINCREMENT, study TEXT NOT NULL, criterion_id TEXT NOT NULL,
 protocol_sha256 TEXT NOT NULL, result_digest TEXT
);
CREATE INDEX IF NOT EXISTS gap_run_scope ON gap_runs(study,criterion_id,protocol_sha256,ticket);
CREATE TABLE IF NOT EXISTS engineering_gaps (
 id TEXT PRIMARY KEY, study TEXT NOT NULL, criterion_id TEXT NOT NULL, protocol_sha256 TEXT NOT NULL,
 fact TEXT NOT NULL, requirements TEXT NOT NULL, status TEXT NOT NULL, catalog_version TEXT NOT NULL,
 first_ticket INTEGER NOT NULL, last_ticket INTEGER NOT NULL, closed_by_rule_sha256 TEXT
);
CREATE INDEX IF NOT EXISTS engineering_scope ON engineering_gaps(study,criterion_id,protocol_sha256,status);
CREATE TABLE IF NOT EXISTS gap_proposals (
 gap_id TEXT NOT NULL REFERENCES engineering_gaps(id), fingerprint TEXT NOT NULL, proposal TEXT NOT NULL,
 PRIMARY KEY(gap_id,fingerprint)
);
"""


def _scope(packet):
    scope = tuple(packet.get(key) for key in _SCOPE_FIELDS)
    if not all(isinstance(s, str) and s.strip() for s in scope) or not re.fullmatch(r"[0-9a-f]{64}", scope[2]):
        raise ValueError("Evidence gaps require a study, criterion ID and protocol SHA-256.")
    return scope


def _normalize(v):
    if isinstance(v, str):
        return " ".join(v.split())
    if isinstance(v, list):
        return [_normalize(item) for item in v]
    if isinstance(v, dict):
        return {k: _normalize(item) for k, item in v.items()}
    return v


class GapLedger:
    """Use begin before slow authoring to order overlapping runs, then pass its ticket to record."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.executescript(_SCHEMA)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _begin(db, scope):
        return db.execute("INSERT INTO gap_runs(study,criterion_id,protocol_sha256) VALUES(?,?,?)",
                          scope).lastrowid

    def begin(self, packet):
        scope = _scope(packet)
        with closing(self._connect()) as db, db:
            return self._begin(db, scope)

    @staticmethod
    def _details(db, row):
        item = dict(row)
        item["requirements"] = json.loads(item["requirements"])
        candidates = db.execute("SELECT proposal FROM gap_proposals WHERE gap_id=? ORDER BY rowid", (row["id"],))
        item["proposals"] = [json.loads(raw[0]) for raw in candidates]
        return item

    def pending(self):
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            rows = db.execute("SELECT * FROM engineering_gaps WHERE status='OPEN' ORDER BY first_ticket,id")
            return [self._details(db, row) for row in rows]

    def record(self, packet, compiled, effective_state, *, ticket=None):
        scope = _scope(packet)
        if tuple(compiled.get(k) for k in _SCOPE_FIELDS) != scope:
            raise ValueError("Compilation and evidence-gap record belong to different protocol scopes.")
        catalog = packet.get("catalog_version")
        if not isinstance(catalog, str) or not catalog.strip() or compiled.get("catalog_version") != catalog:
            raise ValueError("Compilation and evidence-gap record must identify the same catalog.")
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if ticket is None:
                ticket = self._begin(db, scope)
            elif type(ticket) is not int:
                raise ValueError("The evidence-gap run ticket must be an integer.")
            run = db.execute("SELECT * FROM gap_runs WHERE ticket=?", (ticket,)).fetchone()
            if run is None or tuple(run[k] for k in _SCOPE_FIELDS) != scope:
                raise ValueError("Evidence-gap run ticket belongs to another run or protocol scope.")
            newest = db.execute("SELECT max(ticket) FROM gap_runs WHERE " + _FILTER, scope).fetchone()[0]
            if ticket != newest:
                return []
            fingerprint = digest([catalog, effective_state, compiled])
            if run["result_digest"] and run["result_digest"] != fingerprint:
                raise ValueError("Different compilation already recorded for this evidence-gap ticket.")
            db.execute("UPDATE gap_runs SET result_digest=? WHERE ticket=?", (fingerprint, ticket))
            state = compiled.get("state")
            gaps = compiled.get("binding_gaps", [])
            if state == effective_state == "READY":
                rule = compiled.get("executable")
                if (not isinstance(rule, dict) or not rule or compiled.get("rule_sha256") != digest(rule)
                        or not isinstance(compiled.get("queries"), list) or not compiled["queries"]
                        or gaps != [] or compiled.get("questions", []) != []):
                    raise ValueError("Only a compiled rule with its matching digest, queries and no open requirements can close gaps.")
                db.execute("UPDATE engineering_gaps SET status='RESOLVED',last_ticket=?,closed_by_rule_sha256=? "
                           "WHERE status='OPEN' AND " + _FILTER, (ticket, compiled["rule_sha256"], *scope))
                return []
            if effective_state not in _GAP_STATES or state != effective_state:
                return []
            if not isinstance(gaps, list) or not gaps or compiled.get("executable") is not None:
                raise ValueError("Binding review requires an unresolved evidence contract and a withheld executable.")
            changes = {}
            for candidate in gaps:
                if (not isinstance(candidate, dict) or candidate.get("status") != "UNBOUND"
                        or candidate.get("catalog_key") is not None
                        or not isinstance(candidate.get("fact"), str) or not candidate["fact"].strip()):
                    raise ValueError("Invalid unbound evidence contract.")
                contract = _normalize({k: v for k, v in candidate.items() if k not in _PROPOSAL_FIELDS})
                key = "GAP-" + digest([*scope, contract])[:24]
                existing = db.execute("SELECT status FROM engineering_gaps WHERE id=?", (key,)).fetchone()
                reopened = existing is not None and existing["status"] == "RESOLVED"
                if existing is None:
                    db.execute("""INSERT INTO engineering_gaps
                        (id,study,criterion_id,protocol_sha256,fact,requirements,status,catalog_version,first_ticket,last_ticket)
                        VALUES(?,?,?,?,?,?,'OPEN',?,?,?)""",
                        (key, *scope, contract["fact"], json.dumps(contract, ensure_ascii=False), catalog, ticket, ticket))
                else:
                    db.execute("UPDATE engineering_gaps SET status='OPEN',last_ticket=?,catalog_version=?,"
                               "closed_by_rule_sha256=NULL WHERE id=?", (ticket, catalog, key))
                db.execute("INSERT OR IGNORE INTO gap_proposals VALUES(?,?,?)",
                           (key, digest(_normalize(candidate)), json.dumps(candidate, ensure_ascii=False)))
                changes.setdefault(key, "OPENED" if existing is None else "REOPENED" if reopened else "EXISTING")
            result = []
            for key, change in changes.items():
                row = db.execute("SELECT * FROM engineering_gaps WHERE id=?", (key,)).fetchone()
                result.append({**self._details(db, row), "change": change, "is_new": change != "EXISTING"})
            return result
