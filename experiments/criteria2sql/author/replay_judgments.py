"""Replay the two blinded in-session judgments for their exact authoring packet."""
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent


def read(name):
    return json.loads((HERE / name).read_bytes())


def main():
    envelope = json.load(sys.stdin)
    packet = read("packet.json")
    if envelope["task"] == "author":
        answer = read("candidate.json")
    elif envelope["task"] == "verify":
        packet["candidate"] = read("candidate.json")
        answer = read("review.json")
    else:
        raise ValueError("Unknown judgment type")
    if envelope["packet"] != packet:
        raise ValueError("The recorded judgment belongs to a different packet")
    print(json.dumps(answer))


if __name__ == "__main__":
    main()
