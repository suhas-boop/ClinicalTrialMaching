"""Replay an exact recorded author or verifier exchange from the worked examples."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATALOG_DIGEST = "107e4d349f0789e8a9e144f6ee52bc9baef2de62ac1b5039550ef852fcfc02fb"


def load(name):
    return json.loads((HERE / name).read_text())


def replay(envelope):
    packet = envelope["packet"]
    if packet["catalog"]["sha256"] != CATALOG_DIGEST:
        raise ValueError("No recording for the selected catalog.")
    name = next((k for k, v in load("cases.json").items() if v == packet["sources"]), None)
    if name is None:
        raise ValueError("No recording for these exact sources.")
    author = load("author_responses.json")[name]
    if envelope["task"] == "author":
        return author
    if envelope["task"] == "verify" and packet.get("candidate") == author:
        return load("verifier_responses.json")[name]
    raise ValueError("No matching verification recording.")


if __name__ == "__main__":
    print(json.dumps(replay(json.load(sys.stdin))))
