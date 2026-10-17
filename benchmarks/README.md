# Query storage benchmarks

This directory is opt-in. Root `pytest` only collects `tests/`; ordinary CI does
not generate benchmark datasets. No generated CSV, SQLite, RRD or RBL belongs in Git.
Curated JSON/Markdown results may be saved under `results/baselines/`.

## Phase C2a: production Custom Query pushdown

This comparison exercises the production EAV catalog, without DuckDB or schema/index
changes. Field/path/time predicates run in SQL; numeric/text predicates remain in
the original Python filter. Run against retained Phase A input/catalog files:

```bash
python benchmarks/custom_query_pushdown.py --baseline benchmarks/results/baselines/2026-10-06/smoke.json
python benchmarks/custom_query_pushdown.py --baseline benchmarks/results/baselines/2026-10-06/small_index.json
```

The JSON paths describe local artifacts that are not included in Git. If they were
removed, generate an index-only retained baseline using the existing runner with
`--preset smoke --pipeline index-only --keep-dataset --keep-workspace` (or replace
`smoke` with `small`), then supply its JSON to `--baseline`.
No Rerun build is needed for this comparison. Both datasets and catalogs are checked
by SHA256/cardinality/schema before and after; the input catalogs are opened read-only.

Defaults: one warm-up, five measured runs, limit 1000, fresh sequential legacy and
pushdown workers. Legacy explicitly bypasses the new query plan. Reports contain
raw/P50/P95 timings, RSS, production/benchmark code hashes, actual SQL/plans and exact
result parity. An extra untimed pass counts Python-fetched rows and JSON decodes;
these are not engine scan counts. No cache PRAGMA or ANALYZE changes are made.

Acceptance: all three Smoke P95 <= 1 s; each Small P95 at least 2x faster than its
same-run legacy reference. Exit code 2 means correctness passed but the performance
gate failed; the report remains available. Other errors record a failed report.
The repeated Small legacy reference and its counter passes can take tens of minutes.
Only the newly owned run directory is cleaned; retained inputs are never deleted.
This is not a typed-storage, template, compare or diagnostics acceptance result.

Read [the C2a report](../docs/architecture/query-storage-phase-c2a.md) for scope and
compatibility details. The opt-in harness tests include read-only comparison and
failure cleanup checks on tiny datasets.

## Setup

Use Python >= 3.10 and the existing project dependencies. For example:

```bash
python -m pip install -e packages/core -r benchmarks/requirements.txt
python benchmarks/run_benchmark.py --preset smoke
```

On Windows, use `.venv\Scripts\python.exe` if the default `python` is older.
`psutil` is a benchmark dependency only; it is not required by core.

For a quick harness check, use `--rows 256 --query-runs 1 --skip-index-comparison`.
The approximately 10 MB smoke workload can take minutes on current production
query paths, especially with repeated index experiments or `--compare-all`.
It is a small performance baseline, not a guarantee of a seconds-long run.

## Data and presets

The streaming generator writes a CSV with monotonic relative seconds, smooth
position/velocity/current/voltage, slowly changing noisy temperature, declining
battery, idle/running/warning/error states and rare numeric error codes. A fault
at the last sample guarantees an anomaly even in the tiny harness checks.
The seed determines temperature noise; timestamps and anomalies are deterministic.

`--scalar-fields` is the **total telemetry scalar count**, including the ten base
fields (six position/velocity axes, temperature, battery, current and voltage).
It excludes numeric `error_code`. Additional scalars are `scalar_000`, etc.
`--state-fields` includes `robot_state`; additional states are `state_000`, etc.
The timestamp is not indexed as a value. With the inferred scalar/state mapping,
amplification is `scalar_fields + state_fields + 1` (12x, 32x or 102x by default).
Every non-timestamp field is mapped exactly once, checked before building.
Mapping timing includes the real suggestion/validation calls; the harness then
uses explicit `relative_s`, avoiding duration-dependent auto-unit inference.

| Preset | Samples | Frequency | Scalars | Approximate CSV size |
| --- | ---: | ---: | ---: | ---: |
| smoke (default) | 30,000 | 200 Hz | 30 | 10 MB |
| small | 300,000 | 200 Hz | 30 | 100 MB |
| medium | 3,000,000 | 200 Hz | 30 | 1 GB |
| large | 12,000,000 | 200 Hz | 30 | 3–5 GB |

Sizes are estimates, not allocation targets. Actual byte sizes go into the report.
`--rows` overrides preset size; alternatively `--duration` uses
`floor(frequency * duration)`. They are mutually exclusive. For example:

```bash
python benchmarks/generate_dataset.py --frequency 200 --duration 600 \
  --scalar-fields 30 --state-fields 2 --seed 42 --output /tmp/robot.csv
python benchmarks/run_benchmark.py --frequency 200 --duration 600 \
  --scalar-fields 30 --query-runs 7 --output-dir /tmp/datascope-results
```

The generator refuses to overwrite an existing output file.

## Representative matrix

```bash
python benchmarks/run_benchmark.py --matrix --matrix-duration 60
```

| Case | Frequency | Scalars | Samples at 60 seconds | Expected query rows |
| --- | ---: | ---: | ---: | ---: |
| A | 50 Hz | 10 | 3,000 | 36,000 |
| B | 200 Hz | 30 | 12,000 | 384,000 |
| C | 1000 Hz | 30 | 60,000 | 1,920,000 |
| D | 200 Hz | 100 | 12,000 | 1,224,000 |

B/C isolate frequency at a fixed duration; B/D isolate field width at fixed
frequency and duration. B versus smoke/small isolates duration. A also gives a
low-rate, narrow-field reference, but differs from B in two dimensions.
Each matrix case runs sequentially in a fresh process so allocator/OS peak memory
from one case cannot contaminate the next. Increase `--matrix-duration` explicitly
for a larger workload; there is no automatic Cartesian product.

## What is measured

The default `--pipeline full` executes the existing Workspace flow and real Rerun
SDK, without production modifications or fake artifacts. Benchmark-only wrappers
time source import (copy plus checksum), inspect, the nested cold schema profile,
Mapping suggestion, validation, save, recording total, Rerun convert/cleanup,
blueprint, Query Index, executemany and the remaining build overhead.
Timing hooks replace callables directly and release completed insertion batches;
the harness includes a regression check that measurement cannot retain their data.
`inspect_ms` excludes schema profiling; `inspect_total_ms` includes it.
The sample-based schema profile reads 1,000 rows; inspect counts the complete CSV.

For a larger **separate index workload**:

```bash
python benchmarks/run_benchmark.py --preset small --pipeline index-only \
  --skip-diagnostics --skip-index-comparison
```

This still imports/inspects/maps the real CSV and runs production
`_index_recording()` and queries. It registers an explicit benchmark-only
recording fixture. Recording/RRD/RBL metrics are `null`, never fabricated timings.
Its status is distinct from a successful Rerun build. Full mode remains the default.

Storage is measured after a successful WAL checkpoint, before adding the bounded
comparison peer. SQLite/source amplification includes metadata plus all indexes.
`object_size_bytes` separates table/index pages if SQLite provides `dbstat`.
Connection PRAGMAs are recorded rather than assumed: `synchronous` is connection
local, so an initializer setting does not establish the setting of later connections.

Queries use one warm-up and five timed runs by default. All samples, min, mean,
median, nearest-rank P95 and max are saved. Increase `--query-runs` for tail analysis;
with five runs P95 is the maximum. The warm OS cache and existing background load
are part of the experiment; no cold-cache or multi-user claim is made.

- `find_errors`, `low_battery`, `state_duration`, `time_sync` use existing templates.
- Custom queries test scalar key, a narrow late time window and a numeric battery threshold.
- Compare uses battery/temperature against a second **real bounded recording**
  (up to 1,000 samples); peer timings/sizes are separate. This is not two equal
  large recordings. `--compare-all` also measures the current full-field compare.
- Diagnostics invokes the existing implementation on the primary recording.
  `--skip-diagnostics` is explicit because it materializes all general query rows.
- `time_sync` uses a generated MCAP with two actual inspected topics, four messages
  and four production-indexed metadata rows. A benchmark-only catalog fixture
  supplies its recording ID; no auxiliary RRD build is claimed. A known 20 ms
  offset is present in the messages. Current MCAP inspection supplies a shared
  file-wide time range to both topics, so the existing query returns zero deltas.
  The harness checks that current behavior and records this coverage limitation;
  it does not claim the sensor offset was detected. Per-topic ranges are follow-up work.
  `time_sync_csv` separately records the expected empty CSV path. Both reflect
  topic-summary queries, not synchronization of individual scalar samples.

`--query-limit` defaults to 1,000. It bounds returned results; it does not bound
SQLite sorts, state-duration/compare/diagnostics materialization or late custom
filter scans. Result shape, values, counts, adjacent state durations, compare
aggregates, full diagnostics row coverage and stable result hashes are checked
outside each timed query interval. Incorrect runs exit unsuccessfully and are
not decision evidence.

RSS is sampled every 10 ms by `psutil`, including native allocations in this process.
Each phase records before/after/peak RSS. Polling can miss very short spikes;
Windows also records the OS lifetime working-set high-water mark. Child processes
and system file cache are excluded. A fresh process is required for a new baseline.

## Index maintenance versus query benefit

The default isolated experiment uses up to `--index-samples 10000` complete samples
from the first/last halves of the primary recording, preserving normal and anomaly
regions. Every variant starts with a fresh schema/catalog and the exact same rows:
all three indexes, no indexes, or each of the three indexes individually omitted.
Production indexes are never dropped. One committed `INSERT SELECT` isolates SQL
index maintenance without Python parsing/JSON encoding. End-to-end production
index generation is measured separately. Unindexed insertion is followed by
separate timed construction of each index. Each variant also runs the template and
custom queries with warm-ups/repetitions and validates output equality against the
all-index reference. JSON includes production `EXPLAIN QUERY PLAN` details.

This is a bounded, fixed-order experiment with one insert trial per variant. It
cannot alone justify removing an index at GB scale. Use `--index-samples` to expand
it, repeat whole runs and inspect query plans before proposing a production change.
`--skip-index-comparison` avoids repeating that experiment in every matrix case.

## Output and cleanup

Every run writes `benchmark_<UTC time>_<label>_<random id>.json` and `.md` to
`--output-dir` (default `benchmarks/results`). UTC timestamps include an offset.
Environment includes CPU, RAM, Python/package/SQLite versions, Git commit/dirty
state, benchmark-code SHA256 and source checksum. Runs after code changes remain
distinguishable even before committing.

Datasets and workspaces live under the unique `output-dir/.work/<run id>/`.
Success and ordinary exceptions clean up by default. `--keep-dataset` and
`--keep-workspace` retain only their respective primary artifacts; intermediate
peer CSVs and scratch index databases are always removed. A copy-mode retained
workspace has its own raw source copies. Failed runs emit partial JSON/Markdown
with `status=failed`; do not include them in performance conclusions. Force-killing
the process can leave its unique working directory and requires manual cleanup.

## Verify the harness independently

```bash
python -m pytest -q benchmarks/test_benchmark.py
python -m pytest -q
```

The opt-in harness tests use tiny real pipelines. They check deterministic
generation, rows/duration CLI modes, refusal to overwrite, full/index-only
cardinality, query correctness, index equivalence, independent retention flags,
and cleanup/reporting on injected failures while preserving unrelated files.
They also verify completed insertion batches remain collectible during timed indexing.
Ordinary pytest does not collect these tests or run benchmarks.

## Optional Phase B PoC

After obtaining a successful retained SQLite baseline:

```bash
python -m pip install -r benchmarks/requirements-duckdb.txt
python benchmarks/run_benchmark.py --preset smoke --keep-dataset --keep-workspace
python benchmarks/duckdb_poc.py --baseline benchmarks/results/benchmark_<run>.json
```

The PoC checks the original source checksum and validates seven queries against
actual production SQLite results. It compares SQL filtering/window aggregation
on existing SQLite EAV data, a typed wide DuckDB sample table, and ZSTD Parquet
queried by DuckDB. Every generated scalar/state column is retained; field expansion
occurs at query time. The comparison measures layout plus execution changes, not
engines with identical physical models. Production routing and dependencies stay
unchanged. DuckDB defaults to four threads and a 1 GB engine memory limit; total
process RSS is sampled separately. `--query-runs`, `--warmups`, `--threads`,
`--output-dir` and `--keep-artifacts` are configurable. Without the retention flag,
PoC DuckDB/Parquet working files are cleaned on success and ordinary failures.

JSON/Markdown record ingest/checkpoint, Parquet export, each storage size, query
statistics and per-phase memory. The overall memory peak includes the original
SQLite correctness queries. Phase peaks identify each workload's absolute RSS;
retained reference data and earlier allocations prevent independent engine memory
comparisons in this shared process.
Metadata, deletion, concurrency, mixed/null schemas, CV/ROS sample ingestion and
diagnostics parity remain outside this standalone PoC.

Parallel floating-point aggregate means may differ in their last bits. Every
repeat is checked against the production reference with absolute tolerance 1e-8
and relative tolerance 1e-10; aggregate raw hashes and their distinct count are
reported. Other queries retain exact repeated-result hash checks. The original
SQLite catalog is opened read-only and is never initialized or rewritten by PoC.

See `docs/architecture/query-storage-benchmark.md` and the ADR for measured
results, the storage decision, scope limits and future triggers.

## Phase C: optimized SQLite versus DuckDB / Parquet

Install the optional comparison dependencies and run the separate comparison:

```bash
python -m pip install -r benchmarks/requirements-duckdb.txt
python benchmarks/backend_comparison.py --preset smoke --production-control
python benchmarks/backend_comparison.py --preset small
python benchmarks/backend_comparison.py --preset medium
```

To reuse a retained Phase A source, mapping and peer without modifying them:

```bash
python benchmarks/backend_comparison.py --baseline benchmarks/results/baselines/2026-10-06/smoke.json --production-control
```

`--baseline` requires its recorded CSV/workspace paths still to exist. It uses
the baseline dataset parameters and checks the bounded streaming CSV oracle
against all seven actual production queries before launching comparison workers.
Without a baseline, the runner reuses the existing generator, schema inspection
and mapping suggestion, then validates all engines against the independent CSV
oracle. Medium does not require Python materialization of 96 million EAV rows.

Every backend executes in a **fresh sequential process**, with the same input
checksums, query definitions, warm-ups, repetitions, limit and canonical results.
The main Legacy EAV control uses SQL pushdown; the unchanged production Python
execution is explicitly reported as a historical/reference/control path.
Default `--query-runs 5 --warmups 1 --query-limit 1000` can be overridden. Nearest-rank
P95 with five runs remains the maximum observed sample, not a stable tail estimate.
Default peer size is bounded to 1,000 samples; `--peer-rows` can expand newly
generated peers, and the report records the actual aggregate coverage.

The shared normalized layout contains:

- A wide `numeric_samples` row per sample: integer recording key, REAL/DOUBLE
  timestamp, typed numeric columns, integer `error_code`.
- A `state_samples` row per sample with dictionary-encoded state values.
- Small recording, field/path/semantic and state-value dictionaries. Queries
  reconstruct the original strings in SQL. Samples contain no `value_json`.

This avoids persisting one row per field while preserving every mapped value.
The exact same layout is used by Typed SQLite, DuckDB tables and Parquet.
The EAV control persists the existing seven-column `query_rows` model and all
three existing sample indexes in a separate file with the same small dictionaries.
It builds indexes after loading and runs `ANALYZE`; its preparation timings are
not production Recording build timings. No RRD/RBL is built by Phase C.

Typed SQLite tests four index configurations rather than one assumed winner:

| Variant | Sample secondary indexes |
| --- | --- |
| `none` | none |
| `time` | numeric and state `(recording_key, time)` |
| `minimal` | those two, numeric `(recording_key, battery, time)`, state `(recording_key, robot_state, time)` |
| `covering` | same four-index count; replace numeric time index with `(recording_key, time, battery, temperature)` to cover the measured compare metrics |

Dictionary primary keys are present in every variant. Wide columns replace the
long-table `key` dimension, so there is no sample `key` index to repeat for every
field. Key/semantic/path constraints select dictionary-backed SQL branches;
recording, exact/prefix entity path, time bounds, numeric predicates and result
limit remain SQL predicates, with no candidate-value filtering in Python.
Error/warning substring matching runs on the small state-value dictionary and
its matching codes are used by SQL. General text-log/full-text and Unicode case
folding parity are outside the scalar/state fixture.

State duration uses the same safe first `limit + 1` rows per ordered state group
before `LEAD` in all engines; the extra row supplies the last returned duration.
Compare still aggregates every sample for battery and temperature in both
recordings, preserving count/min/max/mean/latest. Exact order, types and values
are compared after canonicalization; floating tolerance reuses the Phase B rules.

Per-worker reports include complete prepare/load/index+analyze/checkpoint costs,
physical rows versus logical samples/values, file bytes, amplification, RSS
before/after/peak, every latency sample and SQL/plans. All durable sizes contain
the samples plus dictionaries; no backend size includes CSV, RRD/RBL or production
workspace metadata. Parquet adds a dictionary manifest and is written directly
from CSV without an extra durable `.duckdb` file. DuckDB reads CSV once per numeric
and state projection (two scans); SQLite's Python CSV loader uses one scan.
Shared generation/schema/oracle/dictionary enumeration costs are separately
reported as setup and are excluded from **all** per-backend preparation columns.

SQLite uses WAL/FULL durability, a 64 MiB connection page cache and file-backed
temporary storage. DuckDB defaults to four threads and a 1 GB engine memory limit;
these are distinct resource settings, not equal internal memory allocations.
Workers use persistent query connections, fixed order and warm filesystem caches.
RSS includes that worker's own preparation, reference data and queries; it does
not mix different engines in one process. No cold-cache/concurrency claim is made.

`--production-control` runs an additional isolated process with the real
`run_custom_query()` function and four repeated execution ablations: SQLite row
iteration, dictionary allocation, JSON decoding, and Python time filtering.
These are observational timings from separate passes, not additive causal shares.
Use this bounded control on Smoke rather than an enormous Python row scan.

`--backends` can restrict development checks, for example
`--backends sqlite_typed_none sqlite_typed_minimal`. Architecture evidence should
contain all seven configurations. Generated files live only under the unique run's
`.work/` directory and are cleaned by default; `--keep-artifacts` retains them.
The runner never deletes retained Phase A inputs or any pre-existing `.work` run.
If cleanup fails, the JSON records the path and error for manual handling.

The standalone `sqlite_typed_poc.py --manifest <retained-run>/manifest.json
--output <new-file>.sqlite --variant minimal` builds just the typed SQLite dataset
and refuses to overwrite an existing database. `time_sync` remains a known
correctness gap; diagnostics backend parity and its 5-second budget are unverified.

After an interrupted run, `--resume-from <prior-phase-c-report>.json` can reuse
completed SQLite preparations without modifying or deleting them. The source
checksums, package/Python/SQLite versions, artifact sizes, dictionaries and row
counts must match. Incomplete preparations are rebuilt in the **new** run only.
All selected queries are measured again in fresh workers; prior build timings,
code hash, date and RSS retain their provenance. A resumed report separates query
worker RSS from retained preparation RSS and reports their maximum as workflow
peak, rather than claiming one newly measured combined process. Source runs and
Phase A/B baselines are never overwritten or cleaned by resuming.

The Phase C query transport has separate DOUBLE and BIGINT channels, preserving
integer values above 2^53 through a mixed-field UNION. The original October 7
partial run only exercised error_code 0/42; a regression test now covers larger
integers on Typed SQLite, DuckDB tables and Parquet. The retained partial report
is historical evidence, not part of the final query comparison.

A single projected field has constant recording/path/key sort terms. The shared
typed compiler drops those constant terms and orders by time, preserving results
while allowing SQLite to use its time index. The earlier full Medium run exposed
a value-index plus sort regression; its results are retained separately, and all
typed paths were remeasured after the common compiler correction. Regression
checks verify that adding value indexes does not introduce a temporary sort for
a bounded scalar lookup.

`--reuse-legacy-control <completed-report>.json` is only for an unchanged EAV
control: exact SQL, source hashes, canonical oracle hashes, query policy and
runtime versions must match. Its original query samples/environment/provenance
remain intact. This avoids repeating an expensive unchanged control after a
typed-only compiler correction; it does not cache or substitute typed results.
