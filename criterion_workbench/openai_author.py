"""stdin/stdout author command using the OpenAI Responses HTTP API and Python's standard library."""

import argparse
import base64
import hashlib
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from author import AUTHOR_INSTRUCTIONS, PUBLIC_PUBLISHERS, PUBLIC_TOPICS


ENDPOINT = "https://api.openai.com/v1/responses"


class ProviderError(RuntimeError):
    def __init__(self, message, partial=""):
        super().__init__(message)
        self.partial = partial


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Credentials are for one fixed origin.


def _send(body, key):
    req = Request(ENDPOINT, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                  headers={"Content-Type":"application/json", "Authorization":"Bearer " + key}, method="POST")
    try:
        with build_opener(_NoRedirect()).open(req, timeout=300) as response:
            raw = response.read().decode("utf-8", "replace")
    except HTTPError as error:
        # Retain provider code, parameter and message; exclude headers and credentials.
        content = error.read().decode("utf-8", "replace").replace(key, "[redacted]")
        try:
            payload = json.loads(content)
            detail = payload.get("error") if isinstance(payload, dict) else None
        except ValueError:
            detail = None
        if isinstance(detail, dict):
            content = json.dumps({k:detail[k] for k in ("type", "code", "param", "message") if k in detail})
        raise ProviderError(f"OpenAI HTTP {error.code}: {content[:4000]}") from None
    except (URLError, TimeoutError, OSError) as error:
        raise ProviderError(f"OpenAI transport failed: {str(error).replace(key, '[redacted]')}") from None
    try:
        value = json.loads(raw)
    except ValueError:
        raise ProviderError("OpenAI returned a non-JSON response.", raw.replace(key, "[redacted]")) from None
    if not isinstance(value, dict):
        raise ProviderError("OpenAI returned an unexpected response envelope.", raw.replace(key, "[redacted]"))
    return value


def _final_text(response):
    output = response.get("output")
    if not isinstance(output, list):
        raise ProviderError("OpenAI response has no output list.")
    messages = [item for item in output if isinstance(item, dict) and item.get("type") == "message"
                and item.get("role") == "assistant"]
    final = messages[-1] if messages else {}
    parts = final.get("content") or []
    text = "".join(x["text"] for x in parts if isinstance(x, dict) and x.get("type") == "output_text"
                   and isinstance(x.get("text"), str))
    refusal = " ".join(str(x.get("refusal", "")) for x in parts if isinstance(x, dict) and x.get("type") == "refusal")
    status = response.get("status")
    if status != "completed" or final.get("status", "completed") != "completed":
        reason = response.get("incomplete_details") or response.get("error") or {}
        raise ProviderError(f"OpenAI response status {status}: {json.dumps(reason)}", text)
    if refusal or not text.strip():
        raise ProviderError("Author response was refused or empty.", refusal or text)
    return text


def _public_terms(topics, model, key):
    instructions = ("Search official publishers for these public topics. Return a JSON object with a candidates "
                    "list. Each record has nonempty strings term, code, system, version and url. Use exact URLs "
                    "from retrieved sources. Omit unverifiable candidates.\n")
    terms = [PUBLIC_TOPICS[k] for k in dict.fromkeys(topics)]
    body = {"model": model, "store": False, "input": instructions + "\n".join(terms),
            "tools": [{"type":"web_search", "filters":{"allowed_domains":list(PUBLIC_PUBLISHERS)}}],
            "tool_choice":"required", "include":["web_search_call.action.sources"]}
    response = _send(body, key)
    text = _final_text(response)
    calls = [x for x in response["output"] if x.get("type") == "web_search_call" and x.get("status") == "completed"]
    if not calls:
        raise ProviderError("Terminology lookup returned without a completed web search.", text)
    sources = {s["url"] for call in calls for s in call.get("action", {}).get("sources", [])
               if isinstance(s, dict) and isinstance(s.get("url"), str)}
    try:
        value = json.loads(text)
        rows = value["candidates"]
        if not isinstance(rows, list):
            raise ValueError()
        result = []
        for row in rows:
            fields = ("term", "code", "system", "version", "url")
            if not isinstance(row, dict) or any(not isinstance(row.get(f), str) or not row[f].strip() for f in fields):
                raise ValueError()
            url = urlsplit(row["url"])
            host = url.hostname or ""
            if (url.scheme != "https" or url.username or url.password or row["url"] not in sources
                    or not any(host == d or host.endswith("." + d) for d in PUBLIC_PUBLISHERS)):
                raise ValueError()
            result.append({k:row[k] for k in fields})
        return result
    except (ValueError, KeyError, TypeError):
        raise ProviderError("Terminology lookup returned unverifiable candidate data.", text) from None


def author_packet(packet, model, key, topics=()):
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Set OPENAI_MODEL or pass --model with a Responses model that supports the source input.")
    if not isinstance(key, str) or not key.strip():
        raise ValueError("Set OPENAI_API_KEY in the author command's environment.")
    file = packet["protocol_attachment"]
    data = file["data_base64"]
    if hashlib.sha256(base64.b64decode(data, validate=True)).hexdigest() != packet["protocol_sha256"]:
        raise ValueError("Protocol attachment does not match the packet's locked digest.")
    ctx = packet["protocol_context"]
    metadata = {k:packet[k] for k in ("criterion_id","study","protocol_sha256","criterion_text","section",
                                      "polarity","catalog_version","catalog","answers","source")}
    metadata["source_locator"] = {k:ctx[k] for k in ("locator","target_page_range","criterion_anchor") if k in ctx}
    if "episode_rule_grammar" in packet:
        metadata["episode_rule_grammar"] = packet["episode_rule_grammar"]
    if file["format"] == "pdf":
        content = [{"type":"input_file", "filename":"protocol.pdf",
                    "file_data":"data:application/pdf;base64," + data}]
    elif file["format"] == "docx":
        content = [{"type":"input_text","text":"Full protocol text with original Word paragraph IDs:\n" + ctx["text"]}]
    else:
        raise ValueError("Unsupported source format.")
    if topics:
        metadata["public_terminology_candidates"] = _public_terms(topics, model, key)
    content.append({"type":"input_text","text":json.dumps(metadata, ensure_ascii=False)})
    body = {"model":model, "store":False, "instructions":AUTHOR_INSTRUCTIONS, "input":[{"role":"user","content":content}],
            "text":{"format":{"type":"json_object"}}}
    return _final_text(_send(body, key))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL"))
    parser.add_argument("--search", action="store_true", help="Use a separate public-only terminology request.")
    parser.add_argument("--topic", action="append", choices=PUBLIC_TOPICS, help="Approved public lookup topic.")
    args = parser.parse_args()
    if bool(args.topic) != args.search:
        parser.error("Use --search together with at least one --topic.")
    key = os.environ.get("OPENAI_API_KEY")
    try:
        text = author_packet(json.load(sys.stdin), args.model, key, args.topic or ())
        sys.stdout.buffer.write(text.encode("utf-8"))
    except ProviderError as error:
        message, partial = str(error), error.partial
        if key:
            message, partial = message.replace(key, "[redacted]"), partial.replace(key, "[redacted]")
        sys.stdout.buffer.write(partial.encode("utf-8"))
        print(message, file=sys.stderr)
        return 1
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
