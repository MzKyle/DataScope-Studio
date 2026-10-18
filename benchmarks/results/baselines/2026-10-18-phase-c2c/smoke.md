# C2c production query backends

Status: succeeded

| Query | EAV P50/P95 ms | C2b compatibility P50/P95 ms | Typed SQL P50/P95 ms |
| --- | ---: | ---: | ---: |
| find_errors | 150.10 / 157.80 | 69.96 / 70.90 | 8.55 / 9.39 |
| low_battery | 1591.01 / 1793.29 | 110.33 / 114.57 | 13.56 / 13.70 |
| custom_scalar_key | 1252.32 / 1508.59 | 6.86 / 7.83 | 7.15 / 9.84 |
| custom_time_range | 499.30 / 626.16 | 4.33 / 5.14 | 4.22 / 4.80 |
| custom_numeric_threshold | 1750.35 / 1880.02 | 145.26 / 148.58 | 15.12 / 19.85 |
| state_duration | 712.38 / 723.43 | 372.98 / 459.64 | 97.34 / 98.67 |
| compare | 3745.23 / 4056.18 | 1501.34 / 1705.48 | 625.58 / 1839.90 |

Acceptance: `{"parity": true, "latency_gates": {"find_errors": true, "low_battery": true, "custom_scalar_key": true, "custom_time_range": true, "custom_numeric_threshold": true}, "latency_required": true, "all_fields_retained": true, "no_eav_fallback": true}`

One catalog, separate sequential read-only query processes; 1 warm-up and 5 samples by default.
Raw JSON contains SQL/EXPLAIN, untimed cursor/candidate/decode counts, RSS, source and code hashes.
Medium latency is report-only. This is not full seven-query or Diagnostics acceptance.
