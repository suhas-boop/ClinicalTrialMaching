import unittest
from chart_links import audit


class ChartLinks(unittest.TestCase):
    def test_local_scope_and_version(self):
        report = {"resourceType":"DiagnosticReport","subject":{"reference":"Patient/a"},
                  "result":[{"reference":x} for x in ("Observation/x","Observation/x/_history/1",
                           "Observation/x/_history/3","Observation/y","urn:uuid:abc")]}
        def obs(id_,version,patient):
            return {"resourceType":"Observation","id":id_,"meta":{"versionId":version},
                    "subject":{"reference":patient}}
        result=audit([report,obs("x","1","Patient/a"),obs("x","2","Patient/a"),obs("y","1","Patient/b")])
        self.assertEqual({"absent_or_ambiguous":2,"linked_same_subject":1,
                          "subject_mismatch_or_missing":1,"unsupported_reference":1},result["reference_checks"])
