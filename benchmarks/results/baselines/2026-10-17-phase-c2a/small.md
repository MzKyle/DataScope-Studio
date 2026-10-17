# Production Custom Query pushdown: benchmark_c2a_20261017_024815_9e44c63d

Status: succeeded.

One warm-up/five runs by default; nearest-rank P95. Separate sequential workers and untimed counters.
Production connections/caches/indexes unchanged; no ANALYZE, migration, new index or Rerun build.

| Query | Legacy P50/P95 ms | Pushdown P50/P95 ms | P95 speedup | Fetched old/new | Decoded old/new |
| --- | ---: | ---: | ---: | ---: | ---: |
| custom_scalar_key | 21467.89 / 21718.12 | 9782.22 / 10468.52 | 2.07× | 30976 / 1000 | 30976 / 1000 |
| custom_time_range | 55135.12 / 164008.77 | 3133.30 / 3696.83 | 44.36× | 9600000 / 352 | 9600000 / 352 |
| custom_numeric_threshold | 146628.88 / 179059.74 | 12675.69 / 13685.92 | 13.08× | 8814293 / 284333 | 8814293 / 284333 |

Gate passed: **True**.

Peak RSS excludes the additional instrumented pass; full SQL, plans, SHA256 and raw samples are in JSON.
