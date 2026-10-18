# Phase C2b production typed SQLite

Date: 2026-10-18 (Asia/Shanghai). Default remains legacy; CSV typed indexes require explicit opt-in.

[Design and limitations](../../../../docs/architecture/query-storage-phase-c2b.md).

| Scale | Source samples | Logical values | Typed sample rows | EAV catalog MB | Typed catalog MB | Typed / CSV | Storage reduction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| smoke | 31,000 | 992,000 | 62,000 | 255.119 | 11.358 | 1.164x | 95.55% |
| small | 301,000 | 9,632,000 | 602,000 | 2478.957 | 115.220 | 1.213x | 95.35% |
| medium | 3,001,000 | 96,032,000 | 6,002,000 | 23610.020 | 1155.514 | 1.216x | 95.11% |

All standard storage gates passed: all 32 fields retained, SQL counts match writer counters, zero EAV fallback, at most two sample rows per source row, catalog <= 2x CSV and >= 80% smaller than EAV.

| Study | Raw JSON | Markdown |
| --- | --- | --- |
| smoke | [smoke.json](smoke.json) | [smoke.md](smoke.md) |
| small | [small.json](small.json) | [small.md](small.md) |
| medium | [medium.json](medium.json) | [medium.md](medium.md) |
| smoke-initial | [smoke-initial.json](smoke-initial.json) | [smoke-initial.md](smoke-initial.md) |

## Method and limits

Smoke/Small use the same retained inputs and mappings, including the 1,000-row peer. The old production catalogs are opened read-only and verified unchanged. Their whole-file storage includes a tiny historical metadata fixture excluded from CSV query selection. Typed storage is the whole fresh checkpointed catalog, including registry, dictionaries, metadata and indexes; it excludes source copies and RRD/RBL.

Each measured query has one warm-up and five samples, in sequential isolated backend processes. P95 is nearest-rank (the maximum of five), not a stable tail SLO. SQL traces, EXPLAIN, counters and candidate counts are gathered in a separate untimed pass. All seven query result digests agree across EAV, typed time and typed none.

Medium reuses the exact Phase C CSVs. Its EAV storage figure is linked historical evidence, not a new production EAV build or same-round query measurement. Medium measures only the production typed index writer and space. All builds here are index-only, not Rerun conversion.

Two time indexes are the production policy. The no-index ablation suppresses only sample CREATE INDEX statements in benchmark-owned scratch storage. The report contains index creation time and allocated pages; whole-file differences between variants include metadata/page rounding and are not exact per-index dbstat sizes. This SQLite build does not expose dbstat.

Small's initial source-file hash snapshot predates the final cancellation/recovery changes and import cleanup. These affect build cancellation paths, not its measured reader SQL, value handling or physical layout; the timed index-only writer does not supply a cancellation signal. Final Smoke and Medium record unchanged start/end production hashes. validation.json records the final tree hashes and complete regression results. No raw report has been rewritten to replace its original hashes.

smoke-initial preserves the first complete Smoke measurement before SQL cardinality counters were added to the runner. It is not substituted for the final Smoke report. In the older Markdown reports, EAV prepare=0.000 means unmeasured (the retained catalog was not rebuilt), not a zero-cost build.

Numeric/text filtering, compare aggregation and Diagnostics still execute in Python. No seven-query 1s or Diagnostics 5s gate is claimed. Per-process RSS excludes setup/other processes and system page cache; the EAV control has query RSS only, while typed workers include index construction and queries.

Reproduction: python -m benchmarks.typed_storage --preset smoke|small|medium. Raw absolute input paths describe this Windows machine; generated datasets/catalogs are not committed. Only each new run's owned work directory is cleaned. All 36 prior committed baseline files remain byte-identical.
