"""Full feedback round trip using synthetic reviewer and model-transport fixtures."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from demo import AGE, EXAMPLES, PROGRESSION, PROGRESSION_RESPONSE, ROOT, SCREEN, call


class FeedbackTests(unittest.TestCase):
    def test_answer_resume_and_recheck_the_same_patient(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            reference = json.loads((EXAMPLES / "age-author.json").read_text())
            probe = {**reference, "disposition":"PROTOCOL_REVIEW", "executable":None,
                     "clinical_questions":[{"id":"QA","question":"Integration control only. Confirm the screening-day age anchor for this simulation.",
                         "cited_source":"Synthetic integration fixture", "intended_owner":"Synthetic reviewer"}]}
            draft = state / "probe.json"
            draft.write_text(json.dumps(probe))
            first = call(state,"run",*AGE,"--response",draft)
            self.assertEqual(first["state"],"PROTOCOL_REVIEW")
            key = first["new_questions"][0]["id"]
            call(state,"answer",key,"--answer","Use the local screening date in this synthetic case.",
                 "--date","2026-11-20","--source","synthetic-test-only","--authority","Simulated QA")
            packet = state / "updated.json"
            update = call(state,"packet",*AGE,"--out",packet)
            self.assertEqual(json.loads(packet.read_text())["answers"][0]["question_id"],key)
            ready_file = state / "updated-response.json"
            ready_file.write_text(json.dumps({"author_input_sha256":update["author_input_sha256"],"response":reference}))
            incomplete = call(state,"resume",first["run_id"],"--response",ready_file)
            self.assertEqual(incomplete["state"],"VALIDATION_HOLD")
            reference["applied_question_ids"] = [key]
            ready_file.write_text(json.dumps({"author_input_sha256":update["author_input_sha256"],"response":reference}))
            completed = call(state,"resume",first["run_id"],"--response",ready_file,
                             "--bundle",EXAMPLES/"patient-age.json",*SCREEN)
            self.assertEqual(completed["parent_run_id"],first["run_id"])
            self.assertEqual(completed["state"],"READY")
            self.assertEqual(completed["patient_result"]["patient_outcome"],"MET")
            self.assertEqual(call(state,"screen",first["run_id"],"--bundle",EXAMPLES/"patient-age.json",*SCREEN)["state"],
                             "REAUTHOR_REQUIRED")

    def test_events_only_stays_quiet_on_identical_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            cmd=[sys.executable,"-B",str(ROOT/"pipeline.py"),"--state-dir",tmp,"run",
                 *PROGRESSION,*PROGRESSION_RESPONSE,"--events-only"]
            first=json.loads(subprocess.check_output(cmd))
            self.assertEqual(len(first["new_questions"]),3)
            self.assertEqual(len(first["new_binding_gaps"]),4)
            self.assertEqual(subprocess.check_output(cmd),b"")
            actions=call(Path(tmp),"actions")
            self.assertEqual((len(actions["coordinator"]),len(actions["engineering"])),(3,4))


if __name__=="__main__":
    unittest.main()
