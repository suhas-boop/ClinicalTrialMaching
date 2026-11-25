"""Evidence work stays separate from coordinator feedback and follows protocol scope."""
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from compiler import digest
from gaps import GapLedger


ROOT = Path(__file__).resolve().parent


class GapLedgerTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.path = Path(self.home.name) / "state.sqlite"
        self.gaps = GapLedger(self.path)
        response = json.loads((ROOT / "examples/i18-author.json").read_text())
        self.packet = {"study": "106S01", **{k: response[k] for k in ("criterion_id", "protocol_sha256", "catalog_version")}}
        self.items = [q for q in response["bindings"] if q["status"] == "UNBOUND"]
        self.compiled = {**self.packet, "state": "PROTOCOL_AND_BINDING_REVIEW",
                         "binding_gaps": self.items, "executable": None}
        self.rule = {"fact": "age", "operator": "ge", "threshold": 18}
        self.ready = {**self.packet, "state": "READY", "rule_sha256": digest(self.rule),
                      "executable": self.rule, "queries": [{"value": "Patient.birthDate"}], "binding_gaps": []}

    def record(self, compiled=None, effective_state=None, ticket=None):
        compiled = self.compiled if compiled is None else compiled
        return self.gaps.record(self.packet, compiled, effective_state or compiled["state"], ticket=ticket)

    def test_actual_i18_draft_retry_and_scoped_marks(self):
        returned = self.record()
        self.assertEqual(len(returned), 4)
        self.assertTrue(all(q["is_new"] for q in returned))
        self.assertTrue(all(len(q["proposals"]) == 1 for q in returned))
        self.assertEqual([q["is_new"] for q in self.record()], [False] * 4)
        self.assertEqual(len(GapLedger(self.path).pending()), 4)
        self.assertEqual(self.record(self.ready), [])
        self.assertEqual(self.gaps.pending(), [])
        reopened = self.record()
        self.assertTrue(all(q["change"] == "REOPENED" for q in reopened))
        self.assertEqual([k["id"] for k in reopened], [k["id"] for k in returned])

    def test_variant_ids_and_proposals_vs_changed_contract(self):
        first = {"id": "P1", "status": "UNBOUND", "fact": "Same   result", "unit": "mg", "proposed_source": "source A"}
        alternative = {**first, "fact": "  Same result ", "id": "P2", "proposed_source":"source B"}
        distinct = {**first, "unit": "g"}
        found = self.record({**self.compiled, "binding_gaps": [first, alternative, distinct]})
        self.assertEqual(len(found), 2)
        self.assertEqual([p["id"] for p in found[0]["proposals"]], ["P1", "P2"])
        self.assertNotEqual(found[0]["id"], found[1]["id"])
        self.assertEqual(found[0]["fact"], "Same result")

    def test_failed_partial_stale_and_unverified_ready_cannot_clear(self):
        self.record()
        self.record({**self.compiled, "binding_gaps": self.items[:1]})
        for state in ("VALIDATION_HOLD", "REAUTHOR_REQUIRED", "RUN_ERROR", "PROTOCOL_REVIEW"):
            self.record(self.ready, state)
        with self.assertRaisesRegex(ValueError, "matching digest"):
            self.record({**self.ready, "rule_sha256":"bad"})
        self.assertEqual(len(self.gaps.pending()), 4)

    def test_overlapping_authors_dont_reopen_or_close(self):
        t1, t2 = self.gaps.begin(self.packet), self.gaps.begin(self.packet)
        self.record(ticket=t2)
        self.assertEqual(self.record(self.ready, ticket=t1), [])
        self.assertEqual(len(self.gaps.pending()), 4)
        t3 = self.gaps.begin(self.packet)
        self.record(self.ready, ticket=t3)
        self.assertEqual(self.record(ticket=t2), [])
        self.assertEqual(self.gaps.pending(), [])
        with self.assertRaisesRegex(ValueError, "Different compilation"):
            self.record(ticket=t3)

    def test_packet_and_ticket_scope(self):
        t1 = self.gaps.begin(self.packet)
        other_scope = {**self.packet, "protocol_sha256":"f"*64}
        other_compiled = {**self.compiled, **other_scope}
        with self.assertRaisesRegex(ValueError, "protocol scope"):
            self.gaps.record(other_scope, other_compiled, other_compiled["state"], ticket=t1)
        with self.assertRaisesRegex(ValueError, "different protocol scopes"):
            self.gaps.record(self.packet, other_compiled, other_compiled["state"])
        self.gaps.record(other_scope, other_compiled, other_compiled["state"])
        self.record(ticket=t1)
        self.assertEqual(len(self.gaps.pending()), 8)
        self.record(self.ready)
        self.assertEqual(len(self.gaps.pending()), 4)
        self.assertEqual({q["protocol_sha256"] for q in self.gaps.pending()}, {"f"*64})

    def test_concurrent_retries_signal_each_gap_once(self):
        def put(_):
            return GapLedger(self.path).record(self.packet, self.compiled, self.compiled["state"])
        with ThreadPoolExecutor(max_workers=5) as pool:
            batches = list(pool.map(put, range(10)))
        self.assertEqual(sum(q["is_new"] for batch in batches for q in batch), 4)
        self.assertEqual(len(self.gaps.pending()), 4)


if __name__ == "__main__":
    unittest.main()
