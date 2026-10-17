# Phase C backend comparison: benchmark_phase_c_20261017_014856_967c1c94

Status: succeeded; samples: 3001000; query runs: 5; warm-ups: 1.

All fresh workers use the same CSV checksums, query limit, full compare aggregates and canonical oracle.
Legacy EAV uses SQL pushdown here; historical production Python filtering is a separate control.

| Backend | Prepare s | Insert/load s | Index + analyze s | MB | Storage amp | Peak RSS MB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| legacy_sqlite_eav | 660.976 | 308.817 | 352.141 | 23610.020 | 24.853 | 276.804 |
| sqlite_typed_none | 36.353 | 35.781 | 0.471 | 938.566 | 0.988 | 203.817 |
| sqlite_typed_time | 38.841 | 36.056 | 2.687 | 1046.921 | 1.102 | 269.902 |
| sqlite_typed_minimal | 43.566 | 37.135 | 6.340 | 1188.671 | 1.251 | 269.529 |
| sqlite_typed_covering | 44.685 | 37.512 | 7.089 | 1243.353 | 1.309 | 269.799 |
| duckdb_table | 4.713 | 4.487 | 0.000 | 233.320 | 0.246 | 676.700 |
| duckdb_parquet | 5.436 | 5.411 | 0.000 | 497.033 | 0.523 | 405.250 |

## Queries (P50 / P95 ms)

| Query | legacy_sqlite_eav | sqlite_typed_none | sqlite_typed_time | sqlite_typed_minimal | sqlite_typed_covering | duckdb_table | duckdb_parquet |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| find_errors | 21897.347 / 25066.593 | 154.201 / 155.985 | 274.264 / 275.906 | 31.084 / 32.757 | 31.970 / 33.284 | 12.004 / 12.442 | 22.568 / 23.089 |
| low_battery | 21973.236 / 22300.341 | 606.001 / 608.989 | 667.756 / 674.022 | 351.308 / 352.729 | 356.498 / 357.567 | 6.183 / 6.663 | 10.740 / 11.610 |
| state_duration | 18.680 / 36.809 | 115.932 / 118.052 | 3.845 / 4.322 | 3.824 / 3.852 | 3.765 / 3.827 | 7.867 / 9.203 | 15.676 / 17.400 |
| custom_scalar_key | 19700.733 / 21068.448 | 661.987 / 677.368 | 197.315 / 201.023 | 2819.902 / 3002.194 | 2793.675 / 2797.916 | 20.373 / 20.498 | 37.095 / 37.765 |
| custom_time_range | 1.329 / 1.399 | 18088.215 / 18747.276 | 1.071 / 1.191 | 1.101 / 1.312 | 1.108 / 1.293 | 11.147 / 11.462 | 77.409 / 81.730 |
| custom_numeric_threshold | 15158.355 / 15274.402 | 608.720 / 614.339 | 659.234 / 662.884 | 118.972 / 120.222 | 116.471 / 117.090 | 5.468 / 5.778 | 8.921 / 9.040 |
| compare | 31681.446 / 31818.427 | 4740.097 / 4816.689 | 1587.751 / 1591.126 | 1209.324 / 1210.757 | 530.916 / 534.833 | 21.556 / 32.043 | 57.884 / 64.984 |

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
