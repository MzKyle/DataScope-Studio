# Phase C backend comparison: benchmark_phase_c_20261007_145014_b79b78cf

Status: running; samples: 3001000; query runs: 5; warm-ups: 1.

All fresh workers use the same CSV checksums, query limit, full compare aggregates and canonical oracle.
Legacy EAV uses SQL pushdown here; historical production Python filtering is a separate control.

| Backend | Prepare s | Insert/load s | Index + analyze s | MB | Storage amp | Peak RSS MB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| legacy_sqlite_eav | 660.976 | 308.817 | 352.141 | 23610.020 | 24.853 | 276.804 |
| sqlite_typed_none | 36.353 | 35.781 | 0.471 | 938.566 | 0.988 | 203.817 |
| sqlite_typed_time | 38.841 | 36.056 | 2.687 | 1046.921 | 1.102 | 269.902 |

## Queries (P50 / P95 ms)

| Query | legacy_sqlite_eav | sqlite_typed_none | sqlite_typed_time |
| --- | ---: | ---: | ---: |
| find_errors | 13528.027 / 13639.245 | 152.576 / 157.230 | 267.399 / 285.355 |
| low_battery | 12319.123 / 12470.618 | 586.864 / 613.215 | 656.148 / 667.692 |
| state_duration | 3.708 / 3.865 | 114.212 / 114.649 | 3.743 / 3.760 |
| custom_scalar_key | 12497.423 / 12514.227 | 625.018 / 628.290 | 191.078 / 193.780 |
| custom_time_range | 1.338 / 1.467 | 16893.975 / 17002.922 | 1.056 / 1.271 |
| custom_numeric_threshold | 12384.696 / 12525.922 | 568.857 / 570.138 | 635.847 / 639.213 |
| compare | 25498.789 / 25654.250 | 4481.616 / 4588.297 | 1566.127 / 1569.360 |

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
- Cleanup: pending.
