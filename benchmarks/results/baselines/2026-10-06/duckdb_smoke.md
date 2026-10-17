# DuckDB / Parquet PoC: duckdb_poc_20261006_033827_abd2b193

Baseline: `D:\Programme\DataScope-Studio\benchmarks\results\benchmark_20261006_031650_baseline_smoke_fixed_c509c566.json`; checksum: `f6d328637d65ddf5d2f5277e507e4142515f96f085559897634601d77d8db895`.

| Metric | Value |
| --- | ---: |
| SQLite Query Index build (primary, ms) | 35005.691 |
| DuckDB CSV ingest + checkpoint (primary + peer, ms) | 436.991 |
| Parquet export (primary + peer, ms) | 113.232 |
| SQLite primary catalog MB | 246.792 |
| SQLite primary + peer live catalog MB | 255.119 |
| DuckDB primary + peer MB | 3.420 |
| Parquet primary + peer MB | 5.529 |
| Process sampled peak RSS MB | 180.699 |

## Query latency

| Query | Production SQLite P50/P95 | SQL pushdown SQLite P50/P95 | DuckDB table P50/P95 | Parquet P50/P95 (ms) |
| --- | ---: | ---: | ---: | ---: |
| find_errors | 486.645/654.914 | 167.934/187.903 | 12.862/15.946 | 55.692/59.578 |
| low_battery | 1672.640/1759.723 | 757.136/853.958 | 15.319/18.647 | 64.604/84.790 |
| custom_scalar_key | 6912.476/7011.658 | 599.536/616.609 | 14.562/17.309 | 65.568/112.519 |
| custom_time_range | 17396.735/17994.574 | 245.118/334.992 | 15.481/18.665 | 72.339/80.553 |
| custom_numeric_threshold | 17106.352/18608.619 | 552.533/614.032 | 14.812/18.269 | 57.703/59.399 |
| state_duration | 580.455/718.611 | 245.487/275.570 | 38.975/50.066 | 68.606/79.721 |
| compare | 3018.905/3420.036 | 608.342/614.796 | 34.365/35.997 | 82.078/109.246 |

## Interpretation and limits

All PoC results are checked against the production SQLite outputs, including ordering,
types, state durations and two-recording aggregates (floating tolerance 1e-8 absolute).
Each aggregate repeat is compared with the production reference (also relative tolerance
1e-10); parallel floating-point means may have different raw hashes at the last bits.
The input source SHA256 must match the baseline. All mapped sample columns are retained.
SQL pushdown uses the current SQLite EAV data and indexes. DuckDB/Parquet use typed wide
samples and expand fields at query time. Gains combine data layout and query pushdown;
they are not a comparison of identical physical models or engines alone.
SQLite size includes catalog metadata/indexes; DuckDB/Parquet sizes contain sample data and
minimal query views. The peer is bounded; two equally large recordings are not tested.
Ingest stages differ: SQLite reparses, expands, JSON-encodes and inserts rows; DuckDB reads
typed CSV columns. Neither PoC path builds Rerun artifacts or changes production routing.
SQL engines run sequentially in fixed order with warm-ups and a warm filesystem cache.
Production SQLite latency comes from the original baseline; background load may differ.
Peak RSS includes the production correctness reference; inspect per-phase RSS in JSON
before attributing the overall peak to DuckDB. DuckDB memory_limit does not cap all process RSS.
The 1 GB DuckDB limit and configurable thread count apply to this experiment only.
Diagnostics, time_sync, null/mixed schemas, deletion/lifecycle and concurrent writers need
a future compatibility prototype. This PoC is not a QueryStore implementation.
