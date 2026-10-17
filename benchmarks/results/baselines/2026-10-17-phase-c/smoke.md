# Phase C backend comparison: benchmark_phase_c_20261017_021738_cdf5a97d

Status: succeeded; samples: 31000; query runs: 5; warm-ups: 1.

All fresh workers use the same CSV checksums, query limit, full compare aggregates and canonical oracle.
Legacy EAV uses SQL pushdown here; historical production Python filtering is a separate control.

| Backend | Prepare s | Insert/load s | Index + analyze s | MB | Storage amp | Peak RSS MB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| legacy_sqlite_eav | 5.405 | 2.879 | 2.504 | 240.464 | 24.641 | 258.290 |
| sqlite_typed_none | 0.427 | 0.386 | 0.004 | 9.703 | 0.994 | 136.462 |
| sqlite_typed_time | 0.453 | 0.401 | 0.023 | 10.768 | 1.103 | 138.334 |
| sqlite_typed_minimal | 0.479 | 0.395 | 0.047 | 12.182 | 1.248 | 138.887 |
| sqlite_typed_covering | 0.495 | 0.402 | 0.049 | 12.751 | 1.307 | 138.215 |
| duckdb_table | 0.549 | 0.327 | 0.000 | 4.993 | 0.512 | 171.319 |
| duckdb_parquet | 0.389 | 0.366 | 0.000 | 5.580 | 0.572 | 153.719 |

## Queries (P50 / P95 ms)

| Query | legacy_sqlite_eav | sqlite_typed_none | sqlite_typed_time | sqlite_typed_minimal | sqlite_typed_covering | duckdb_table | duckdb_parquet |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| find_errors | 66.247 / 70.309 | 4.062 / 4.247 | 3.867 / 4.134 | 3.897 / 4.188 | 3.932 / 4.098 | 4.177 / 4.566 | 5.307 / 5.649 |
| low_battery | 64.524 / 64.696 | 4.559 / 5.010 | 3.864 / 4.258 | 3.857 / 4.642 | 2.920 / 3.123 | 3.019 / 3.670 | 4.400 / 4.703 |
| state_duration | 3.940 / 4.052 | 4.993 / 5.312 | 3.978 / 4.020 | 3.789 / 3.880 | 3.629 / 3.673 | 5.165 / 5.398 | 5.837 / 5.958 |
| custom_scalar_key | 66.977 / 67.269 | 4.061 / 4.330 | 2.369 / 2.652 | 2.407 / 2.541 | 2.514 / 3.536 | 3.093 / 3.357 | 4.376 / 4.866 |
| custom_time_range | 1.280 / 1.354 | 31.220 / 32.980 | 1.090 / 1.108 | 1.077 / 1.154 | 1.053 / 1.064 | 7.173 / 7.619 | 36.168 / 39.077 |
| custom_numeric_threshold | 65.114 / 65.232 | 4.095 / 4.827 | 4.160 / 4.326 | 4.001 / 4.228 | 3.017 / 3.487 | 2.732 / 2.820 | 4.201 / 4.221 |
| compare | 134.571 / 136.526 | 8.857 / 9.550 | 6.357 / 7.133 | 7.712 / 7.849 | 4.515 / 4.667 | 3.901 / 4.056 | 10.810 / 11.054 |

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
