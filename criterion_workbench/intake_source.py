"""Source-anchored author input for a previously unindexed study PDF."""

import base64
import hashlib
import json
import re
import unicodedata
from copy import deepcopy

from author import AUTHOR_INSTRUCTIONS, RUNTIME, _pdf_context, scoped_answers


REQUIRED = ("study", "criterion_id", "polarity", "criterion_text", "section",
            "pdf_page", "protocol_version", "protocol_sha256")
OPTIONAL = {"synthetic_fixture", "context_pages"}


def _normalized(text):
    # Retain inequality signs, digits and punctuation when matching the author's selection.
    return " ".join(unicodedata.normalize("NFC", text).split())


def _manifest(value):
    if not isinstance(value, dict):
        raise ValueError("Intake manifest must be a JSON object.")
    if set(REQUIRED) - value.keys():
        raise ValueError("Missing intake fields: " + ", ".join(sorted(set(REQUIRED) - value.keys())))
    if value.keys() - set(REQUIRED) - OPTIONAL:
        raise ValueError("Unknown intake fields: " + ", ".join(sorted(value.keys() - set(REQUIRED) - OPTIONAL)))
    m = deepcopy(value)
    for key in REQUIRED:
        if key == "pdf_page":
            continue
        if not isinstance(m[key], str) or not m[key].strip():
            raise ValueError("Missing or empty intake field " + key)
        m[key] = m[key].strip()
    if m["polarity"] not in {"inclusion", "exclusion"}:
        raise ValueError("Specify inclusion or exclusion polarity.")
    if type(m["pdf_page"]) is not int or m["pdf_page"] < 1:
        raise ValueError("pdf_page must be a positive integer.")
    if not re.fullmatch(r"[a-f0-9]{64}", m["protocol_sha256"]):
        raise ValueError("protocol_sha256 must be the lowercase SHA-256 of the original PDF.")
    if type(m.get("synthetic_fixture", False)) is not bool:
        raise ValueError("synthetic_fixture must be a boolean.")
    if "context_pages" in m:
        pages = m["context_pages"]
        if not isinstance(pages, list) or any(type(i) is not int or i < 1 for i in pages):
            raise ValueError("context_pages must contain positive, one-based page numbers.")
        m["context_pages"] = sorted(set(pages))
    inventory = json.loads((RUNTIME / "inventory.json").read_bytes())
    studies = {s.casefold() for s in inventory["studies"]}
    criteria = {r["id"].casefold() for r in inventory["criteria"]}
    if m["study"].casefold() in studies or m["criterion_id"].casefold() in criteria:
        raise ValueError("This study or criterion already exists in the baseline inventory.")
    return m


def _row(m):
    return {"id": m["criterion_id"], "study": m["study"], "polarity": m["polarity"],
            "section": m["section"], "pdf_pages": [m["pdf_page"], m["pdf_page"]],
            "context_pages": m.get("context_pages", []), "extracted_text": m["criterion_text"]}


def _source_anchor(raw, manifest):
    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError("Install PyMuPDF to verify a PDF source.") from exc
    needle = _normalized(manifest["criterion_text"])
    # Reject a match ending inside a word or number, such as '21' inside '210' or '21.5'.
    pattern = re.compile(r"(?<!\w)(?=(" + re.escape(needle) + r")(?!\w))")
    matches = []
    try:
        original = pymupdf.open(stream=raw, filetype="pdf")
    except (RuntimeError, ValueError) as exc:
        raise ValueError("The original protocol PDF is unreadable.") from exc
    with original as doc:
        if doc.needs_pass:
            raise ValueError("The supplied PDF is encrypted; its criterion text could not be verified.")
        page = manifest["pdf_page"]
        if not 1 <= page <= len(doc):
            raise ValueError("The manifest page is outside the source PDF.")
        if manifest.get("synthetic_fixture") and "SYNTHETIC RESEARCH FIXTURE" not in doc[0].get_text():
            raise ValueError("The first page does not carry the required synthetic-fixture marker.")
        for block in doc[page - 1].get_text("blocks", sort=True):
            if block[6] != 0:
                continue
            text = _normalized(block[4])
            for match in pattern.finditer(text):
                suffix = text[match.end(1):]
                if needle[-1].isdigit() and re.match(r"[.,]\d", suffix):
                    continue
                matches.append({"pdf_page": page, "source_paragraph": text,
                                "match_start": match.start(1), "match_end": match.end(1)})
    if len(matches) != 1:
        raise ValueError(f"Expected one exact normalized criterion match in a source paragraph on page {page}; found {len(matches)}.")
    return matches[0]


def build_intake_packet(manifest, pdf_bytes, answers):
    """Construct author input from one declared source locator and the complete original study PDF."""
    m = _manifest(manifest)
    if not isinstance(pdf_bytes, bytes) or hashlib.sha256(pdf_bytes).hexdigest() != m["protocol_sha256"]:
        raise ValueError("The supplied PDF does not match protocol_sha256.")
    if b"%PDF-" not in pdf_bytes[:1024]:
        raise ValueError("The supplied bytes do not identify a PDF.")
    anchor = _source_anchor(pdf_bytes, m)
    context = _pdf_context(pdf_bytes, _row(m))
    context["criterion_anchor"] = anchor
    catalog = json.loads((RUNTIME / "catalog.json").read_bytes())
    return {
        "schema": "pocketmd-author-input-v1", "source_mode": "uploaded_pdf", "intake_manifest": m,
        "study": m["study"], "criterion_id": m["criterion_id"], "criterion_text": m["criterion_text"],
        "protocol_sha256": m["protocol_sha256"], "polarity": m["polarity"], "section": m["section"],
        "synthetic_fixture": m.get("synthetic_fixture", False),
        "source": {"version": m["protocol_version"], "protocol_sha256": m["protocol_sha256"],
                   "protocol_member": "protocol.pdf", "origin": "submitted PDF and study manifest"},
        "protocol_context": context, "protocol_attachment": {"format": "pdf",
            "data_base64": base64.b64encode(pdf_bytes).decode("ascii")},
        "catalog_version": catalog["version"], "catalog": catalog, "instructions": AUTHOR_INSTRUCTIONS,
        "answers": scoped_answers(m["criterion_id"], m["study"], m["protocol_sha256"], answers),
    }


def validated_row(packet):
    """Rebuild source, original page image, full text, catalog and scoped workflow input before release."""
    if not isinstance(packet, dict) or packet.get("source_mode") != "uploaded_pdf":
        raise ValueError("External source validation requires an uploaded PDF packet.")
    attachment = packet.get("protocol_attachment")
    if (not isinstance(attachment, dict) or attachment.get("format") != "pdf"
            or not isinstance(attachment.get("data_base64"), str)):
        raise ValueError("The original source PDF attachment is required.")
    try:
        raw = base64.b64decode(attachment["data_base64"], validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid encoded source PDF.") from exc
    rebuilt = build_intake_packet(packet.get("intake_manifest"), raw, packet.get("answers"))
    if json.dumps(rebuilt, sort_keys=True, allow_nan=False) != json.dumps(packet, sort_keys=True, allow_nan=False):
        raise ValueError("Author packet fields differ from the verified PDF, manifest, catalog or source context.")
    return _row(rebuilt["intake_manifest"])
