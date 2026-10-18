# Phase C2c production query backends

These reports compare the production C2a EAV reader, a frozen C2b compatibility
reader, and the C2c typed SQL filtering reader. The compatibility and SQL workers
read the same checkpointed typed catalog in separate sequential read-only
processes. Each query has one warm-up and five measured samples; validation,
tracing, EXPLAIN and counting run outside the timing intervals.

Smoke/Small reuse their original retained CSVs and immutable EAV catalogs.
Medium uses the retained Phase C CSVs and measures five filters; no same-round
Medium EAV build/query or complete seven-query latency claim is made.

| Typed SQL query P95 ms | Smoke | Small | Medium (report only) |
| --- | ---: | ---: | ---: |
| find_errors | 9.39 | 34.45 | 284.46 |
| low_battery | 13.70 | 65.08 | 2075.09 |
| custom_scalar_key | 9.84 | 7.08 | 46.72 |
| custom_time_range | 4.80 | 4.58 | 24.45 |
| custom_numeric_threshold | 19.85 | 75.30 | 2432.17 |

Both hard-gate scales pass every filter's P95 <= 1000 ms. All seven result
digests agree across EAV, compatibility and SQL. All 32 fields are retained,
with zero EAV fallback. Small compare remains 13192.19 ms P95 and state duration
3856.03 ms; their original full-input Python algorithms are retained.

Medium's five result digests agree across compatibility and SQL. Its compatibility
find_errors/low_battery/numeric-threshold P95 values are 26745.29/44753.74/65955.77 ms.
The two numeric filters still exceed 1 second on Medium. Key/time queries are
slightly slower than compatibility in this run, while remaining below 50 ms;
there is no claim that every query improved. Production catalog preparation took
549.74 seconds; the typed SQL query process peaked at 103.17 MB RSS.

The late window returns 352 logical values from 22 distinct dataset/time samples.
Each numeric-threshold SQL run fetches/decodes 1000 matched values instead of
sending the preceding nonmatches to Python. The JSON distinguishes returned
projection rows, time candidates, matching SQL candidates and business decodes.
SQLite rows/pages examined are unavailable and explicitly null.

The unchanged two sample time indexes are used; no value/covering indexes or
storage migration are introduced. New query execution is automatic for supported
typed data; construction still defaults to legacy. Diagnostics optimization and
the full default-switch performance gates remain future work.

Each raw JSON/Markdown pair is copied byte-for-byte from its ad-hoc report.
`validation.json` records provenance, source hashes, regression results and the
unchanged prior baseline blobs. All previous benchmark baselines are retained.
P95 is nearest-rank over five samples (the maximum), describing this machine's
sequential warm-cache run, not a stable production tail SLO.

See the [implementation and remaining work](../../../../docs/architecture/query-storage-phase-c2c.md).
