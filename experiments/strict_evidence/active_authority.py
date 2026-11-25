"""Print the current authority worklist as CSV from the reviewed questions and dispositions."""
import csv
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent


def scope(row):
    return row["study"], row["case"], row["role"]


def main():
    dispositions = json.loads((HERE / "authority_dispositions.json").read_bytes())
    dormant = {scope(row) for row in dispositions if row["status"] == "dormant"}
    with (HERE / "reviews" / "authority_questions.csv").open(newline="") as source:
        questions = csv.DictReader(source)
        active = csv.DictWriter(sys.stdout, fieldnames=questions.fieldnames)
        active.writeheader()
        active.writerows(row for row in questions if scope(row) not in dormant)


if __name__ == "__main__":
    main()
