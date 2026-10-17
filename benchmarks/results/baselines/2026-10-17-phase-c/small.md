# Phase C backend comparison: benchmark_phase_c_20261017_021931_c8397461

Status: succeeded; samples: 301000; query runs: 5; warm-ups: 1.

All fresh workers use the same CSV checksums, query limit, full compare aggregates and canonical oracle.
Legacy EAV uses SQL pushdown here; historical production Python filtering is a separate control.

| Backend | Prepare s | Insert/load s | Index + analyze s | MB | Storage amp | Peak RSS MB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| legacy_sqlite_eav | 55.485 | 28.838 | 26.565 | 2343.031 | 24.667 | 260.661 |
| sqlite_typed_none | 3.936 | 3.862 | 0.038 | 94.056 | 0.990 | 202.576 |
| sqlite_typed_time | 5.102 | 3.701 | 0.245 | 104.878 | 1.104 | 210.403 |
| sqlite_typed_minimal | 4.313 | 3.725 | 0.547 | 119.050 | 1.253 | 211.358 |
| sqlite_typed_covering | 4.308 | 3.680 | 0.596 | 124.535 | 1.311 | 216.408 |
| duckdb_table | 1.021 | 0.791 | 0.000 | 29.897 | 0.315 | 326.820 |
| duckdb_parquet | 0.959 | 0.936 | 0.000 | 51.289 | 0.540 | 270.856 |

## Queries (P50 / P95 ms)

| Query | legacy_sqlite_eav | sqlite_typed_none | sqlite_typed_time | sqlite_typed_minimal | sqlite_typed_covering | duckdb_table | duckdb_parquet |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| find_errors | 628.194 / 637.743 | 17.145 / 18.313 | 17.670 / 18.453 | 17.607 / 17.904 | 17.846 / 18.595 | 5.546 / 5.689 | 7.581 / 8.075 |
| low_battery | 634.472 / 650.816 | 61.854 / 64.153 | 55.624 / 62.104 | 56.977 / 58.945 | 9.434 / 9.691 | 3.674 / 3.892 | 5.395 / 6.281 |
| state_duration | 3.926 / 4.433 | 15.055 / 16.048 | 3.858 / 4.465 | 3.576 / 3.754 | 3.798 / 3.897 | 5.266 / 5.596 | 7.613 / 8.499 |
| custom_scalar_key | 652.594 / 654.563 | 61.700 / 62.505 | 2.235 / 2.400 | 2.451 / 2.746 | 2.344 / 2.502 | 3.578 / 3.841 | 7.200 / 7.717 |
| custom_time_range | 1.318 / 1.408 | 1746.139 / 1782.862 | 1.070 / 1.207 | 1.226 / 1.300 | 1.119 / 1.239 | 8.741 / 9.716 | 43.222 / 45.509 |
| custom_numeric_threshold | 633.980 / 636.069 | 61.481 / 62.258 | 62.041 / 63.235 | 66.296 / 67.637 | 10.375 / 10.685 | 3.218 / 3.287 | 4.837 / 5.121 |
| compare | 1295.316 / 1302.216 | 463.213 / 476.904 | 159.010 / 163.836 | 136.563 / 140.520 | 42.955 / 43.991 | 4.863 / 4.882 | 15.564 / 16.149 |

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
- Cleanup: {'status': 'removed_owned_run_directory'}.
