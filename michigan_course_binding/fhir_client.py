"""Loopback-only FHIR transport reused from the PocketMD R4 standardization test."""
import json, uuid
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

class FHIR:
    def __init__(self, url):
        self.base = url.rstrip("/") + "/"
        self.origin = urlsplit(self.base).netloc
        if urlsplit(url).hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Use a disposable loopback server for these synthetic writes.")
        self.http = build_opener(ProxyHandler({}))
        self.prefix = "pmd-" + uuid.uuid4().hex[:8] + "-"

    def call(self, path, body=None, method="GET"):
        url = urljoin(self.base, path)
        if urlsplit(url).netloc != self.origin:
            raise ValueError("Unexpected host in search result")
        headers = {"Accept": "application/fhir+json", "Cache-Control": "no-cache"}
        raw = None
        if body is not None:
            headers["Content-Type"] = "application/fhir+json"
            raw = json.dumps(body).encode()
        request = Request(url, data=raw, headers=headers, method=method)
        try:
            with self.http.open(request, timeout=45) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except HTTPError as exc:
            detail = exc.read().decode()[:1500]
            raise RuntimeError(f"{method} {path} HTTP {exc.code} {detail}") from exc

