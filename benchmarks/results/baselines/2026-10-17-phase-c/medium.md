# Phase C backend comparison: benchmark_phase_c_20261017_021213_c329c481

Status: succeeded; samples: 3001000; query runs: 5; warm-ups: 1.

All fresh workers use the same CSV checksums, query limit, full compare aggregates and canonical oracle.
Legacy EAV uses SQL pushdown here; historical production Python filtering is a separate control.

| Backend | Prepare s | Insert/load s | Index + analyze s | MB | Storage amp | Peak RSS MB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| legacy_sqlite_eav | 660.976 | 308.817 | 352.141 | 23610.020 | 24.853 | 276.804 |
| sqlite_typed_none | 36.353 | 35.781 | 0.471 | 938.566 | 0.988 | 203.817 |
| sqlite_typed_time | 38.841 | 36.056 | 2.687 | 1046.921 | 1.102 | 269.902 |
| sqlite_typed_minimal | 43.391 | 36.930 | 6.360 | 1188.671 | 1.251 | 269.234 |
| sqlite_typed_covering | 43.665 | 36.623 | 6.955 | 1243.353 | 1.309 | 267.919 |
| duckdb_table | 4.373 | 4.130 | 0.000 | 234.369 | 0.247 | 704.799 |
| duckdb_parquet | 5.332 | 5.307 | 0.000 | 497.033 | 0.523 | 389.120 |

## Queries (P50 / P95 ms)

| Query | legacy_sqlite_eav | sqlite_typed_none | sqlite_typed_time | sqlite_typed_minimal | sqlite_typed_covering | duckdb_table | duckdb_parquet |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| find_errors | 21897.347 / 25066.593 | 144.955 / 149.026 | 215.959 / 218.839 | 218.075 / 234.792 | 219.960 / 222.106 | 7.979 / 8.679 | 20.392 / 21.406 |
| low_battery | 21973.236 / 22300.341 | 573.303 / 580.499 | 526.787 / 530.765 | 535.653 / 540.360 | 121.163 / 123.547 | 3.872 / 3.919 | 7.948 / 8.781 |
| state_duration | 18.680 / 36.809 | 117.510 / 119.045 | 3.879 / 4.132 | 3.762 / 3.921 | 3.613 / 3.923 | 7.452 / 7.945 | 15.988 / 16.177 |
| custom_scalar_key | 19700.733 / 21068.448 | 579.234 / 593.519 | 2.485 / 2.576 | 2.445 / 2.507 | 2.267 / 2.454 | 7.249 / 7.477 | 24.361 / 25.376 |
| custom_time_range | 1.329 / 1.399 | 17186.423 / 17630.205 | 1.138 / 1.210 | 1.109 / 1.135 | 1.047 / 1.124 | 10.136 / 10.862 | 74.558 / 76.870 |
| custom_numeric_threshold | 15158.355 / 15274.402 | 566.609 / 570.046 | 596.297 / 597.930 | 604.890 / 607.249 | 135.507 / 136.646 | 3.298 / 3.882 | 6.693 / 6.701 |
| compare | 31681.446 / 31818.427 | 4471.906 / 4479.510 | 1557.985 / 1562.632 | 1188.888 / 1196.673 | 532.254 / 537.740 | 19.530 / 19.827 | 57.255 / 67.608 |

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
