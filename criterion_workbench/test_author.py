"""Author-input and model transport checks; no network or credentials needed."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import author


class AuthorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        data = io.BytesIO()
        with ZipFile(data, "w") as doc:
            doc.writestr("word/document.xml", f'<w:document xmlns:w="{author.W[1:-1]}" '
                         f'xmlns:w14="{author.W14[1:-1]}"><w:body><w:p w14:paraId="0001">'
                         '<w:r><w:t>PRIVATE-FIXTURE criterion.</w:t></w:r></w:p></w:body></w:document>')
        self.raw = data.getvalue()
        self.digest = hashlib.sha256(self.raw).hexdigest()
        with ZipFile(self.root / "source.zip", "w") as archive:
            archive.writestr("sample.docx", self.raw)
        self.row = {"study": "TEST", "id": "TEST-I01", "extracted_text": "PRIVATE-FIXTURE criterion.",
                    "polarity": "inclusion", "section": "Eligibility",
                    "locator": {"part":"word/document.xml", "word_paragraph_id":"0001"}}
        self.inventory = {"studies": {"TEST": {"protocol_sha256": self.digest, "protocol_member": "sample.docx",
                                              "version": "v1"}}, "criteria": [self.row]}
        (self.root / "inventory.json").write_text(json.dumps(self.inventory))
        (self.root / "catalog.json").write_text('{"version":"test-v1","mappings":[]}')
        patched = patch.object(author, "RUNTIME", self.root)
        patched.start()
        self.addCleanup(patched.stop)

    def packet(self, answers=()):
        return author.build_packet("TEST-I01", self.root / "source.zip", answers)

    def test_source_lock_and_scoped_answers(self):
        answer = dict(criterion_id="TEST-I01", protocol_sha256=self.digest, question="Is the boundary inclusive?",
                      answer="yes", authority="synthetic", source_reference="test-source", decision_date="2026-11-20")
        packet = self.packet([answer])
        self.assertEqual(packet["answers"], [answer])
        self.assertIn("[0001] PRIVATE-FIXTURE", packet["protocol_context"]["text"])
        for field in ("protocol_sha256", "criterion_id"):
            with self.assertRaises(ValueError):
                self.packet([{**answer, field:"incorrect"}])
        wrong = self.root / "different.zip"
        with ZipFile(wrong, "w") as archive:
            archive.writestr("sample.docx", b"change")
        with self.assertRaisesRegex(ValueError, "amendment"):
            author.build_packet("TEST-I01", wrong, [])

    def test_subprocess_exact_output_and_error(self):
        self.assertEqual(author.generate(self.packet(), [sys.executable, "-c",
                         "import json,sys; d=json.load(sys.stdin); print(d['study'])"]), "TEST\n")
        with self.assertRaises(author.AuthorCommandError) as raised:
            author.generate(self.packet(), [sys.executable, "-c",
                            "import sys; print('partial'); print('reason',file=sys.stderr); sys.exit(3)"])
        self.assertEqual((raised.exception.returncode, raised.exception.stdout, raised.exception.stderr),
                         (3, "partial\n", "reason\n"))

    def test_cli_adapter_uses_distinct_public_and_private_contexts(self):
        cli = self.root / "codex"
        cli.write_text("""#!/usr/bin/env python3
import json,sys
from pathlib import Path
args=sys.argv[1:]
prompt=sys.stdin.read()
out=Path(args[args.index('--output-last-message')+1])
if '--search' in args:
    assert not list(Path.cwd().iterdir())
    assert 'PRIVATE-FIXTURE' not in prompt and 'NCI' in prompt
    assert 'shell_tool' in args
    out.write_text('[{"term":"PD","code":"C35571","system":"NCIt","version":"fixture","url":"https://evs.nci.nih.gov/"}]')
else:
    packet=json.loads(Path('task.json').read_text())
    assert packet['criterion_text'].startswith('PRIVATE-FIXTURE')
    assert Path('protocol.docx').is_file() and 'web_search="disabled"' in args
    assert packet['public_terminology_candidates'][0]['term']=='PD'
    out.write_text('{"completed": true}\\n')
""")
        cli.chmod(0o700)
        with patch.dict(os.environ, {"PATH":str(self.root)+os.pathsep+os.environ["PATH"]}):
            output = author.generate(self.packet(), [sys.executable, author.__file__, "codex", "--search",
                                                    "--topic", "response"])
        self.assertEqual(output, '{"completed": true}\n')


if __name__ == "__main__":
    unittest.main()
