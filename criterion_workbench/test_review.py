"""Regression tests for research clarification identity and attributed feedback."""
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

from review import ReviewQueue


ROOT = Path(__file__).resolve().parent


class ReviewQueueTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.path = Path(self.home.name) / "reviews.sqlite"
        self.queue = ReviewQueue(self.path)
        self.draft = json.loads((ROOT / "examples/i18-author.json").read_text())
        self.packet = {"study": "106S01", "criterion_id": self.draft["criterion_id"],
                       "protocol_sha256": self.draft["protocol_sha256"]}

    def test_registration_and_attribution_replay(self):
        initial = self.queue.register(self.packet, self.draft)
        self.assertEqual(initial[0]["id"], "SOTIO-PROGRESSION")
        self.assertTrue(all(r["is_new"] for r in initial))
        self.assertEqual(len({q["id"] for q in initial}), 3)
        self.assertEqual(self.queue.answers(self.packet), [])
        reopened = ReviewQueue(self.path)
        retry = reopened.register(self.packet, self.draft)
        self.assertFalse(any(q["is_new"] for q in retry))
        self.assertEqual([q["id"] for q in initial], [q["id"] for q in retry])
        answer = ("Synthetic only", "QA fixture", "2026-11-20", "synthetic-case/ref")
        reopened.answer(initial[0]["id"], *answer)
        reopened.answer(initial[0]["id"], *answer)
        self.assertEqual(len(reopened.pending()), 2)
        self.assertEqual(self.queue.answers(self.packet)[0]["source_reference"], answer[3])
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            reopened.answer(initial[0]["id"], "Changed answer", *answer[1:])
        self.assertEqual(self.queue.answers(self.packet)[0]["answer"], answer[0])

    def test_archive_text_and_generated_question_match_in_either_order(self):
        q = json.loads((ROOT / "runtime/coordinator_questions.json").read_text())["106S01"][1]
        canonical = dict(self.draft, clinical_questions=[{"id": "Q9", "question": q["question"]}])
        first = self.queue.register(self.packet, canonical)[0]
        later = self.queue.register(self.packet, self.draft)[0]
        self.assertEqual(first["id"], later["id"])
        self.assertFalse(later["is_new"])

    def test_amendment_and_scope_isolation(self):
        old_id = self.queue.register(self.packet, self.draft)[0]["id"]
        self.queue.answer(old_id, "Fixture", "Reviewer", "2026-11-20", "Fixture reference")
        for changed in ({"protocol_sha256": "b" * 64}, {"criterion_id": "different"}, {"study": "other"}):
            new_packet = dict(self.packet, **changed)
            new_draft = dict(self.draft, criterion_id=new_packet["criterion_id"], protocol_sha256=new_packet["protocol_sha256"])
            new = self.queue.register(new_packet, new_draft)
            self.assertTrue(all(x["is_new"] and x["status"] == "OPEN" for x in new))
            self.assertEqual(self.queue.answers(new_packet), [])
            self.assertEqual(len(self.queue.open_for(new_packet)), 3)
            self.assertNotIn(old_id, [x["id"] for x in new])

    def test_altered_qualifier_and_local_id_reuse(self):
        first = self.queue.register(self.packet, self.draft)
        different = deepcopy(self.draft["clinical_questions"][0])
        different.update(existing_question_id=first[0]["id"], possible_answers=["Changed scope"])
        second = self.queue.register(self.packet, dict(self.draft, clinical_questions=[different]))[0]
        self.assertNotEqual(second["id"], first[0]["id"])
        self.assertEqual(second["possible_duplicate_of"], first[0]["id"])
        reinjected = dict(self.draft, clinical_questions=[dict(self.draft["clinical_questions"][1], id="Q1")])
        self.assertEqual(self.queue.register(self.packet, reinjected)[0]["id"], first[1]["id"])

    def test_partial_batch_rolls_back(self):
        draft = dict(self.draft, clinical_questions=[self.draft["clinical_questions"][0], None])
        with self.assertRaises(ValueError):
            self.queue.register(self.packet, draft)
        self.assertEqual(self.queue.pending(), [])
        with self.assertRaises(ValueError):
            self.queue.register(self.packet, dict(self.draft, protocol_sha256="e" * 64))
        self.assertEqual(self.queue.pending(), [])

    def test_concurrent_retries_and_conflicting_answers(self):
        def register(_):
            return ReviewQueue(self.path).register(self.packet, self.draft)
        with ThreadPoolExecutor(max_workers=6) as workers:
            batches = list(workers.map(register, range(18)))
        self.assertEqual(sum(r["is_new"] for rows in batches for r in rows), 3)
        token = batches[0][0]["id"]

        def answer(index):
            try:
                return self.queue.answer(token, f"fixture-{index}", "QA", "2026-11-20", "Synthetic source")["answer"]
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=6) as workers:
            results = [value for value in workers.map(answer, range(10)) if value is not None]
        self.assertEqual(results, [self.queue.answers(self.packet)[0]["answer"]])

    def test_invalid_answer_cannot_close_question(self):
        q = self.queue.register(self.packet, self.draft)[0]["id"]
        for dt, src in (("2026-02-30","source"),("20261120","source"),("2026-11-20"," ")):
            with self.assertRaises(ValueError):
                self.queue.answer(q, "answer", "authority", dt, src)
        self.assertEqual(len(self.queue.open_for(self.packet)), 3)


if __name__ == "__main__":
    unittest.main()
