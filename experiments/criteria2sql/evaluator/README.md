# Criteria2SQL development reference

The source is Xiaojing Yu and colleagues’ Criteria2SQL release. Development JSONL line 242 contains the criterion, a query string, a structured SQL annotation, a phase field and a table identifier. The corresponding synthetic table schema appears on line 50 of the development table file. The dataset paper describes its preprocessed trial criteria, SQL annotation and synthetic patient tables. [Dataset paper, §3.2](https://aclanthology.org/2020.lrec-1.714/) · [Pinned source files](https://github.com/xiaojingyu92/Criteria2SQL/tree/045528d70a7d788775a24763adfed6c66023c914/data)

`reference.jsonl` preserves the exact bytes of the selected development line, including its terminator. `schema.json` contains its table ID, ordered headers and types. The synthetic screening patients used by this experiment come from the frozen local controls.

The scoring replay runs offline. To independently verify both upstream SHA-256 checksums, both Git blob IDs, the exact selected line and the ordered schema, supply the two complete original development files to `verify_source.py`. From the PocketMD directory, a networked machine can run the following commands.

```sh
data_dir="$(mktemp -d)"
revision=045528d70a7d788775a24763adfed6c66023c914
base="https://raw.githubusercontent.com/xiaojingyu92/Criteria2SQL/$revision/data"
curl -fsSL "$base/dev.jsonl" -o "$data_dir/dev.jsonl"
curl -fsSL "$base/dev.tables.jsonl" -o "$data_dir/dev.tables.jsonl"
python3 -B experiments/criteria2sql/evaluator/verify_source.py "$data_dir"
```

## Scoring

The released query is `select id from records where age >= 18`. The verifier runs it verbatim against an in-memory SQLite table named `records`, with the published column order and corresponding SQLite types. Every complete row independently supplies the two fields read by the query, `id` and `age`. Other columns are unused. Only complete controls enter SQL. The separate missing-age control is scored for PocketMD abstention.

The release also encodes the query as `{"agg":0,"sel":0,"conds":[[6,3,"18"]]}`. In the source schema column 0 is `id` and column 6 is `age`. In the release operator table, aggregation 0 means no aggregation and comparison 3 means greater than or equal. The scorer runs a second parameterized statement decoded from those source fields and records both ID lists. [Release operator definitions](https://github.com/xiaojingyu92/Criteria2SQL/blob/045528d70a7d788775a24763adfed6c66023c914/src/sqlnet/dbengine.py)

The verifier checks the SHA-256 of the pre-scoring freeze, each manifest input and output, and the content-addressed rule. It audits both chart and flat source identity, the birth date, study encounter, local calendar date, snapshot cutoff, and exact references cited by each FHIR decision. Each case records the age under the alternative UTC and cutoff anchors. The saved score includes disagreements, false definitive decisions and abstentions by branch.

```sh
python3 -B experiments/criteria2sql/evaluator/score.py \
  --freeze experiments/criteria2sql/author/frozen \
  --out /tmp/criteria2sql-new-score
```
