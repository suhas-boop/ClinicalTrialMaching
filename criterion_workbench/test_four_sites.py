"""Two reference-replay CLI checks covering the REC and Michigan runtime adapters."""
import json
from pathlib import Path
import tempfile
import unittest

from demo import EXAMPLES, call

CASES = EXAMPLES / "compat"


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / "state"

    def test_rec_adolescent_performance_status(self):
        screening = ["--patient","demo","--encounter","screen","--as-of","2026-05-01T19:00:00Z"]
        run = call(self.state, "run","REC-1245-101-I05","--site",CASES/"REC-1245-101-protocol.zip",
                   "--response",CASES/"rec-reference-draft.json","--bundle",CASES/"rec-patient.json",*screening)
        self.assertEqual(run["state"], "READY", run.get("reason"))
        self.assertEqual(run["patient_result"]["patient_outcome"],"MET")
        chart = json.loads((CASES/"rec-patient.json").read_text())
        score = next(r["resource"] for r in chart["entry"] if r["resource"]["resourceType"]=="Observation")
        self.assertIn(f"Observation/{score['id']}/_history/1",run["patient_result"]["evidence"])
        score["valueInteger"]=60
        variant = Path(self.temp.name)/"lower.json"
        variant.write_text(json.dumps(chart))
        below = call(self.state,"screen",run["run_id"],"--bundle",variant,*screening)
        self.assertEqual(below["patient_outcome"],"NOT_MET")

    def test_michigan_index_episode(self):
        screening = ["--patient","demo-compat-met-p","--episode","demo-compat-met-current",
                     "--as-of","2026-04-15T12:00:00Z"]
        run = call(self.state,"run","MI-LMS-01","--site",CASES/"NCT05653388-protocol.zip",
                   "--response",CASES/"mi-reference-draft.json","--bundle",CASES/"mi-patient.json",*screening)
        self.assertEqual(run["state"],"READY",run.get("reason"))
        self.assertEqual(run["patient_result"]["patient_outcome"],"MET")
        self.assertIn("Condition/demo-compat-met-current/_history/1",run["patient_result"]["evidence"])
        chart = json.loads((CASES/"mi-patient.json").read_text())
        metastatic = next(r["resource"] for r in chart["entry"]
                          if r["resource"]["id"] == "demo-compat-met-metastatic")
        metastatic["focus"] = [{"reference":"Condition/demo-compat-met-prior"}]
        wrong_episode = Path(self.temp.name)/"other-episode.json"
        wrong_episode.write_text(json.dumps(chart))
        replay = call(self.state,"screen",run["run_id"],"--bundle",wrong_episode,*screening)
        self.assertEqual(replay["patient_outcome"],"MISSING_DATA")


if __name__ == "__main__":
    unittest.main()
