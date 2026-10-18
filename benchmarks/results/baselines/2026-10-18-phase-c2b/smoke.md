# C2b production typed storage

Status: succeeded

| Backend | Catalog MB | Peak RSS MB | Prepare s |
| --- | ---: | ---: | ---: |
| eav | 255.119 | 151.847 | n/a |
| typed_time | 11.358 | 129.888 | 2.184 |
| typed_none | 10.076 | 129.438 | 2.138 |

| Query | EAV P50/P95 ms | Typed time P50/P95 ms | Typed none P50/P95 ms |
| --- | ---: | ---: | ---: |
| find_errors | 151.51 / 153.23 | 241.56 / 296.62 | 125.91 / 203.89 |
| low_battery | 904.05 / 1228.64 | 352.79 / 513.97 | 402.41 / 442.60 |
| state_duration | 425.88 / 449.55 | 235.23 / 282.03 | 248.05 / 351.64 |
| custom_scalar_key | 751.74 / 893.66 | 29.64 / 62.08 | 39.54 / 84.36 |
| custom_time_range | 248.16 / 291.48 | 10.83 / 13.10 | 335.22 / 362.66 |
| custom_numeric_threshold | 1209.69 / 1420.52 | 480.31 / 536.91 | 376.13 / 548.94 |
| compare | 2389.22 / 2522.44 | 1123.33 / 1264.21 | 1097.97 / 1129.55 |

Acceptance: `{"gates": {"typed_rows_at_most_two_per_sample": true, "writer_counts_match_sql": true, "all_values_retained": true, "no_eav_fallback": true, "storage_at_most_2x_csv": true, "storage_reduced_at_least_80_percent": true}, "storage_amplification": 1.163889508555169, "storage_reduction": 0.9554788472344866, "query_latency_gates": "not a C2b storage acceptance condition"}`

Raw JSON includes every timing sample, SQL/EXPLAIN, untimed counts, source/code hashes and storage objects.
This measures index construction and compatibility queries, not Rerun build or Diagnostics performance.
