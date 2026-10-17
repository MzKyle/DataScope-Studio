# Phase C2a production Custom Query results

Date: 2026-10-17. Production metadata/time predicate pushdown; original numeric/text filtering retained.
[Architecture report](../../../../docs/architecture/query-storage-phase-c2a.md).

| Study | Raw JSON | Markdown |
| --- | --- | --- |
| Smoke | [smoke.json](smoke.json) | [smoke.md](smoke.md) |
| Small | [small.json](small.json) | [small.md](small.md) |

## Results

| Dataset / Query | Legacy P50 / P95 ms | Production P50 / P95 ms | P95 speedup | Fetched old / new | JSON decodes old / new |
| --- | ---: | ---: | ---: | ---: | ---: |
| smoke / custom_scalar_key | 2206.62 / 2268.77 | 306.76 / 313.86 | 7.23× | 30,976 / 1,000 | 30,976 / 1,000 |
| smoke / custom_time_range | 5238.17 / 5275.93 | 107.36 / 108.32 | 48.70× | 960,000 / 352 | 960,000 / 352 |
| smoke / custom_numeric_threshold | 5241.62 / 5267.80 | 415.55 / 418.26 | 12.59× | 909,293 / 29,333 | 909,293 / 29,333 |
| small / custom_scalar_key | 21467.89 / 21718.12 | 9782.22 / 10468.52 | 2.07× | 30,976 / 1,000 | 30,976 / 1,000 |
| small / custom_time_range | 55135.12 / 164008.77 | 3133.30 / 3696.83 | 44.36× | 9,600,000 / 352 | 9,600,000 / 352 |
| small / custom_numeric_threshold | 146628.88 / 179059.74 | 12675.69 / 13685.92 | 13.08× | 8,814,293 / 284,333 | 8,814,293 / 284,333 |

Small 旧路径 time-window 的五个原始样本（秒）为 54.152 / 54.194 / 55.135 / 151.100 / 164.009；P50/P95 均展示，不将最慢样本解释成稳定尾延迟。三类查询的 P50 提速最小为 2.19 倍。

Smoke: all three P95 <= 1 s. Small: all three P95 speedups >= 2x versus same-run legacy. Both gates passed.
Exact result hashes match; database/source SHA256, size, schema, version and cardinality unchanged.

## Reproduction

```bash
python benchmarks/custom_query_pushdown.py --baseline benchmarks/results/baselines/2026-10-06/smoke.json
python benchmarks/custom_query_pushdown.py --baseline benchmarks/results/baselines/2026-10-06/small_index.json
```

Absolute artifact paths in JSON describe this local run; the large datasets/catalogs are ignored and not shipped in Git.
New work directories were cleaned by each run. Historical retained inputs were neither deleted nor rewritten.

## Measurement and limits

- Separate sequential legacy/pushdown workers, one warm-up and five measured runs; nearest-rank P95 is max of five.
- Persistent data unchanged; production connections/cache PRAGMAs/indexes, no ANALYZE or schema migration.
- SQL result metadata selection happens in production; numeric/text comparisons remain in the original Python function.
- Formal RSS/latency exclude the separate counter pass. Fetched rows count Python-consumed rows, not engine scans.
- CPU, versions, source/database/code hashes, SQL/plans, all raw timings and RSS are included in JSON.
- Fixed order and warm filesystem caches; single-machine synthetic CSV, no cold/concurrent/Medium/Large claim.
- This is not a typed-storage, template, compare or diagnostics acceptance result.

## Validation

Python: 282 passed / 5 skipped; opt-in benchmark harness: 19 passed; targeted query/API suite: 78 passed.
Desktop: 69 passed, tsc/Vite build passed. Compileall, release sanity and diff check passed.
Original 31 Phase A/B/C baseline files remain byte-identical. No production test was relaxed to pass the benchmark.
