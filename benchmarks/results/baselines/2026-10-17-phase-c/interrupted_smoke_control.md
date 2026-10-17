# Phase C backend comparison: benchmark_phase_c_20261017_020703_29cfbc6b

Status: running; samples: 31000; query runs: 5; warm-ups: 1.

All fresh workers use the same CSV checksums, query limit, full compare aggregates and canonical oracle.
Legacy EAV uses SQL pushdown here; historical production Python filtering is a separate control.

| Backend | Prepare s | Insert/load s | Index + analyze s | MB | Storage amp | Peak RSS MB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| legacy_sqlite_eav | 6.050 | 3.342 | 2.684 | 240.464 | 24.641 | 257.937 |
| sqlite_typed_none | 0.457 | 0.417 | 0.004 | 9.703 | 0.994 | 136.278 |
| sqlite_typed_time | 0.458 | 0.408 | 0.023 | 10.768 | 1.103 | 137.302 |
| sqlite_typed_minimal | 0.480 | 0.403 | 0.046 | 12.182 | 1.248 | 138.228 |
| sqlite_typed_covering | 0.479 | 0.394 | 0.051 | 12.751 | 1.307 | 138.289 |
| duckdb_table | 0.546 | 0.330 | 0.000 | 4.993 | 0.512 | 158.069 |
| duckdb_parquet | 0.391 | 0.368 | 0.000 | 5.580 | 0.572 | 153.633 |

## Queries (P50 / P95 ms)

| Query | legacy_sqlite_eav | sqlite_typed_none | sqlite_typed_time | sqlite_typed_minimal | sqlite_typed_covering | duckdb_table | duckdb_parquet |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| find_errors | 75.766 / 102.321 | 4.138 / 4.270 | 4.449 / 4.692 | 3.023 / 3.397 | 2.923 / 3.098 | 5.164 / 5.297 | 6.340 / 6.550 |
| low_battery | 74.998 / 81.199 | 4.594 / 5.228 | 4.754 / 5.243 | 6.298 / 8.154 | 5.884 / 6.280 | 3.405 / 3.546 | 4.824 / 6.047 |
| state_duration | 4.723 / 4.976 | 5.106 / 5.301 | 3.930 / 4.445 | 3.703 / 4.068 | 3.847 / 4.286 | 5.180 / 5.558 | 5.835 / 6.351 |
| custom_scalar_key | 69.794 / 73.677 | 4.841 / 5.162 | 4.519 / 4.584 | 26.851 / 27.306 | 26.217 / 26.450 | 3.822 / 4.150 | 5.566 / 6.199 |
| custom_time_range | 1.261 / 1.304 | 32.914 / 33.795 | 1.203 / 1.293 | 1.093 / 1.321 | 1.090 / 1.109 | 7.379 / 7.672 | 37.573 / 37.879 |
| custom_numeric_threshold | 67.321 / 67.575 | 4.013 / 5.098 | 4.757 / 5.466 | 3.308 / 3.829 | 3.320 / 3.664 | 3.526 / 3.913 | 4.525 / 4.831 |
| compare | 137.977 / 139.398 | 9.890 / 10.354 | 7.011 / 7.239 | 8.127 / 8.567 | 4.450 / 4.713 | 3.988 / 4.165 | 10.888 / 11.124 |

## Method and limits

- Sizes contain all numeric/state samples plus small dictionaries. Source CSV, RRD/RBL and production metadata are excluded for every backend.
- Typed SQLite, DuckDB tables and Parquet use the same wide numeric and state-code layout; all fields are retained.
- SQLite cache: 64 MiB; temp files allowed; WAL/FULL build durability. DuckDB settings and exact SQL/plans are in JSON.
- Legacy schema/indexes match query_rows, but its isolated preparation builds indexes after ingestion. It is not a production Recording build timing.
- SQLite index timing includes ANALYZE. DuckDB scans CSV separately for numeric and state data; Parquet is written directly without a second durable DuckDB database.
- One backend per fresh process, sequential execution, persistent query connection, warm cache, fixed order. RSS includes that backend's preparation, validation and queries only.
- Query timing includes execute/fetch/decode/canonicalization; parity checks and hashes are outside the timer. All raw samples are retained; P95 is nearest-rank.
- State duration applies the same safe per-group limit + one look-ahead row before LEAD for all backends. Compare aggregates every sample in both recordings.
- Floating tolerance: absolute 1e-8 / relative 1e-10; output order, keys, strings and integer values are preserved.
- time_sync: known correctness gap in production MCAP file-wide ranges. Diagnostics backend parity is not implemented or used to claim a 5 s pass.
- Synthetic smooth, non-null CSV scalar/state data only; no multi-writer, null/mixed/CV/ROS/lifecycle/packaging validation.
- Resumed preparations retain their original build date/code/RSS; queries are all remeasured. Workflow RSS is the larger observed build/query peak, not a new joint-process measurement.
- Cleanup: pending.
