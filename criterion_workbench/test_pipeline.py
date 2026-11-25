"""End-to-end CLI checks. Every synthetic decision is confined to a temporary directory."""
import json
import shlex
import sys
import tempfile
import unittest
from pathlib import Path

from demo import AGE, AGE_RESPONSE, EXAMPLES, PROGRESSION, PROGRESSION_RESPONSE, SCREEN, age_cases, call


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.state = self.work / "state"

    def test_age_cases_through_cli(self):
        run, cases = age_cases(self.state)
        self.assertEqual(run["state"], "READY")
        self.assertEqual(cases, {"eighteenth_birthday":"MET", "one_day_under":"NOT_MET",
                                 "birth_date_missing":"MISSING_DATA"})
        self.assertIn("Patient/synthetic-age-example/_history/1",run["patient_result"]["evidence"])

    def test_generated_questions_feedback_and_stale_response(self):
        first = call(self.state, "run", *PROGRESSION, *PROGRESSION_RESPONSE)
        self.assertEqual(first["state"], "PROTOCOL_AND_BINDING_REVIEW")
        self.assertEqual(len(first["new_questions"]), 3)
        self.assertEqual(len(first["binding_gaps"]), 4)
        repeat = call(self.state, "run", *PROGRESSION, *PROGRESSION_RESPONSE)
        self.assertEqual(repeat["new_questions"], [])
        self.assertEqual(len(call(self.state, "questions")), 3)
        original_input = first["author_input_sha256"]
        call(self.state, "answer", "SOTIO-PROGRESSION", "--answer", "Synthetic test only: progression in window.",
             "--authority", "Synthetic QA", "--date", "2026-11-20", "--source", "synthetic:test-record")
        self.assertEqual(len(call(self.state, "questions")), 2)
        exported = self.work / "updated-packet.json"
        packet = call(self.state, "packet", *PROGRESSION, "--out", exported)
        self.assertNotEqual(packet["author_input_sha256"], original_input)
        answers = json.loads(exported.read_text())["answers"]
        self.assertEqual([(a["question_id"], a["authority"],a["source_reference"]) for a in answers],
                         [("SOTIO-PROGRESSION","Synthetic QA","synthetic:test-record")])
        stale = call(self.state,"screen",first["run_id"],"--bundle",EXAMPLES/"patient-age.json",*SCREEN)
        self.assertEqual(stale["state"], "REAUTHOR_REQUIRED")
        self.assertIsNone(stale["patient_outcome"])
        old = self.work / "old-envelope.json"
        old.write_text(json.dumps({"author_input_sha256":original_input,
                                   "response":json.loads((EXAMPLES/"i18-author.json").read_text())}))
        refused = call(self.state,"run",*PROGRESSION,"--response",old,expected_exit=1)
        self.assertEqual(refused["state"], "RUN_ERROR")
        self.assertNotIn("patient_result",refused)

    def test_author_command_input_excludes_patient_data(self):
        # Transport probe: this local executable deliberately replays a saved author response.
        seen = self.work / "model-input.json"
        probe = self.work / "author-probe.py"
        probe.write_text("from pathlib import Path\nimport sys\n"
                         "Path(sys.argv[1]).write_bytes(sys.stdin.buffer.read())\n"
                         "sys.stdout.buffer.write(Path(sys.argv[2]).read_bytes())\n")
        command = shlex.join([sys.executable,str(probe),str(seen),str(EXAMPLES/"age-author.json")])
        result = call(self.state,"run",*AGE,"--author-command",command,
                      "--bundle",EXAMPLES/"patient-age.json",*SCREEN)
        raw = seen.read_text()
        self.assertEqual(result["patient_result"]["patient_outcome"],"MET")
        self.assertEqual(json.loads(raw)["criterion_id"],"NEOK001-1-I02")
        self.assertNotIn("synthetic-age-example",raw)
        self.assertNotIn("2008-11-20",raw)

    def test_malformed_response_is_preserved_without_execution(self):
        malformed = self.work / "malformed.txt"
        malformed.write_text("incomplete {")
        result = call(self.state,"run",*AGE,"--response",malformed,"--bundle",EXAMPLES/"patient-age.json",
                      *SCREEN,expected_exit=1)
        self.assertEqual(result["state"],"RUN_ERROR")
        self.assertNotIn("patient_result",result)
        recorded = self.state/"runs"/result["run_id"]/"first-response.txt"
        self.assertEqual(recorded.read_text(),malformed.read_text())
        self.assertEqual(call(self.state,"questions"),[])


if __name__ == "__main__":
    unittest.main()
