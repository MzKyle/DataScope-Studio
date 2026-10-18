# C3 full Diagnostics

Status: succeeded

| Path | P50 ms | P95 ms |
| --- | ---: | ---: |
| eav_new | 261992.77 | 271600.07 |
| typed_old | 167919.86 | 177995.25 |
| typed_new | 4314.42 | 4521.28 |

Raw JSON preserves complete reports, raw timings, RSS, SQL/EXPLAIN and separate counters.
Medium uses exact original rules one CSV group at a time; no all-field row list.
Acceptance: {"exact_report_parity": true, "typed_p95_le_5s": true, "latency_required": true, "all_32_fields": true, "read_only_catalogs": true}
