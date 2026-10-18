# C2b production typed storage

Status: succeeded

| Backend | Catalog MB | Peak RSS MB | Prepare s |
| --- | ---: | ---: | ---: |
| eav | 255.119 | 150.688 | 0.000 |
| typed_time | 11.358 | 128.885 | 2.235 |
| typed_none | 10.076 | 130.425 | 2.158 |

| Query | EAV P50/P95 ms | Typed time P50/P95 ms | Typed none P50/P95 ms |
| --- | ---: | ---: | ---: |
| find_errors | 151.00 / 151.69 | 276.25 / 295.05 | 113.71 / 283.57 |
| low_battery | 985.83 / 1116.46 | 408.18 / 501.37 | 325.38 / 405.17 |
| state_duration | 471.73 / 574.52 | 273.78 / 334.42 | 238.68 / 301.58 |
| custom_scalar_key | 1046.67 / 1082.90 | 18.51 / 42.98 | 37.47 / 59.68 |
| custom_time_range | 224.91 / 372.82 | 10.44 / 35.67 | 458.45 / 573.91 |
| custom_numeric_threshold | 1335.18 / 1413.07 | 516.21 / 571.98 | 464.88 / 645.28 |
| compare | 2440.68 / 2678.88 | 1027.54 / 1232.74 | 1041.77 / 1126.98 |

Acceptance: `{"gates": {"typed_rows_at_most_two_per_sample": true, "all_values_retained": true, "no_eav_fallback": true, "storage_at_most_2x_csv": true, "storage_reduced_at_least_80_percent": true}, "storage_amplification": 1.163889508555169, "storage_reduction": 0.9554788472344866, "query_latency_gates": "not a C2b storage acceptance condition"}`

Raw JSON includes every timing sample, SQL/EXPLAIN, untimed counts, source/code hashes and storage objects.
This measures index construction and compatibility queries, not Rerun build or Diagnostics performance.
