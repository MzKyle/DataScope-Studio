# C2c production query backends

Status: succeeded

| Query | EAV P50/P95 ms | C2b compatibility P50/P95 ms | Typed SQL P50/P95 ms |
| --- | ---: | ---: | ---: |
| find_errors | 4590.30 / 5441.42 | 2022.47 / 2446.22 | 33.30 / 34.45 |
| low_battery | 12442.77 / 12536.30 | 3872.34 / 4140.48 | 64.72 / 65.08 |
| custom_scalar_key | 9339.17 / 9589.78 | 26.54 / 49.90 | 6.92 / 7.08 |
| custom_time_range | 3124.18 / 3273.88 | 16.66 / 21.77 | 4.19 / 4.58 |
| custom_numeric_threshold | 14543.25 / 15181.65 | 6146.79 / 6288.59 | 74.19 / 75.30 |
| state_duration | 6683.30 / 8227.18 | 3481.04 / 3552.17 | 3448.28 / 3856.03 |
| compare | 27857.07 / 33610.95 | 12212.54 / 12792.52 | 13003.63 / 13192.19 |

Acceptance: `{"parity": true, "latency_gates": {"find_errors": true, "low_battery": true, "custom_scalar_key": true, "custom_time_range": true, "custom_numeric_threshold": true}, "latency_required": true, "all_fields_retained": true, "no_eav_fallback": true}`

One catalog, separate sequential read-only query processes; 1 warm-up and 5 samples by default.
Raw JSON contains SQL/EXPLAIN, untimed cursor/candidate/decode counts, RSS, source and code hashes.
Medium latency is report-only. This is not full seven-query or Diagnostics acceptance.
