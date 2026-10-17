# Production Custom Query pushdown: benchmark_c2a_20261017_024630_17ee87cc

Status: succeeded.

One warm-up/five runs by default; nearest-rank P95. Separate sequential workers and untimed counters.
Production connections/caches/indexes unchanged; no ANALYZE, migration, new index or Rerun build.

| Query | Legacy P50/P95 ms | Pushdown P50/P95 ms | P95 speedup | Fetched old/new | Decoded old/new |
| --- | ---: | ---: | ---: | ---: | ---: |
| custom_scalar_key | 2206.62 / 2268.77 | 306.76 / 313.86 | 7.23× | 30976 / 1000 | 30976 / 1000 |
| custom_time_range | 5238.17 / 5275.93 | 107.36 / 108.32 | 48.70× | 960000 / 352 | 960000 / 352 |
| custom_numeric_threshold | 5241.62 / 5267.80 | 415.55 / 418.26 | 12.59× | 909293 / 29333 | 909293 / 29333 |

Gate passed: **True**.

Peak RSS excludes the additional instrumented pass; full SQL, plans, SHA256 and raw samples are in JSON.
