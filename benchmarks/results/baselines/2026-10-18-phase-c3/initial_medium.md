# C3 full Diagnostics

Status: succeeded

| Path | P50 ms | P95 ms |
| --- | ---: | ---: |
| typed_new | 41478.89 | 43467.81 |

Raw JSON preserves complete reports, raw timings, RSS, SQL/EXPLAIN and separate counters.
Medium uses exact original rules one CSV group at a time; no all-field row list.
Acceptance: {"exact_report_parity": true, "typed_p95_le_5s": false, "latency_required": false, "all_32_fields": true, "read_only_catalogs": true}
