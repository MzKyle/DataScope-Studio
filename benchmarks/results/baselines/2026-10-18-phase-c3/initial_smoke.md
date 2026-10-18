# C3 full Diagnostics

Status: succeeded

| Path | P50 ms | P95 ms |
| --- | ---: | ---: |
| eav_old | 19789.61 | 20234.93 |
| eav_new | 23974.90 | 24461.30 |
| typed_old | 17437.48 | 18010.96 |
| typed_new | 169.01 | 175.76 |

Raw JSON preserves complete reports, raw timings, RSS, SQL/EXPLAIN and separate counters.
Medium uses exact original rules one CSV group at a time; no all-field row list.
Acceptance: {"exact_report_parity": true, "typed_p95_le_5s": true, "latency_required": true, "all_32_fields": true, "read_only_catalogs": true}
