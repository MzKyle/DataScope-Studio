# Isolated SQLite index experiment

Extracted isolated fresh SQLite INSERT/query experiment. No insertion Mock is used here; main pipeline timing/RSS from this early run is excluded.

Source run: benchmark_20261006_015545_baseline_smoke_41538061; checksum: f6d328637d65ddf5d2f5277e507e4142515f96f085559897634601d77d8db895

## Isolated index experiment

Same 10,000 complete first/last source samples (320,000 query rows) replayed into each fresh catalog.
INSERT SELECT excludes parsing; this is separate from the end-to-end index build.
One insert trial per variant; query min/mean/P50/P95/max and EXPLAIN plans are in JSON.

| Index set | INSERT ms | SQLite MB | low_battery P95 ms | custom range P95 ms |
| --- | ---: | ---: | ---: | ---: |
| all | 3,689.721 | 82.391 | 454.487 | 5,897.857 |
| none | 943.004 | 35.647 | 432.428 | 4,376.232 |
| without_idx_query_rows_recording | 2,905.775 | 71.016 | 586.756 | 6,445.144 |
| without_idx_query_rows_key | 3,212.895 | 75.698 | 460.199 | 6,606.261 |
| without_idx_query_rows_recording_semantic_key | 2,395.063 | 53.715 | 537.361 | 4,914.729 |

Deferred index construction after unindexed INSERT:
- `idx_query_rows_recording`: 453.649 ms
- `idx_query_rows_key`: 246.879 ms
- `idx_query_rows_recording_semantic_key`: 1,290.197 ms


Full query samples, plans and phase RSS are in index_experiment.json.
