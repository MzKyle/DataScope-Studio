# C2c production query backends

Status: succeeded

| Query | EAV P50/P95 ms | C2b compatibility P50/P95 ms | Typed SQL P50/P95 ms |
| --- | ---: | ---: | ---: |
| find_errors | n/a | 21613.48 / 26745.29 | 282.40 / 284.46 |
| low_battery | n/a | 41659.26 / 44753.74 | 1890.80 / 2075.09 |
| custom_scalar_key | n/a | 23.44 / 28.32 | 17.21 / 46.72 |
| custom_time_range | n/a | 9.46 / 10.99 | 16.90 / 24.45 |
| custom_numeric_threshold | n/a | 42637.54 / 65955.77 | 2199.24 / 2432.17 |

Acceptance: `{"parity": true, "latency_gates": {"find_errors": true, "low_battery": false, "custom_scalar_key": true, "custom_time_range": true, "custom_numeric_threshold": false}, "latency_required": false, "all_fields_retained": true, "no_eav_fallback": true}`

One catalog, separate sequential read-only query processes; 1 warm-up and 5 samples by default.
Raw JSON contains SQL/EXPLAIN, untimed cursor/candidate/decode counts, RSS, source and code hashes.
Medium latency is report-only. This is not full seven-query or Diagnostics acceptance.
