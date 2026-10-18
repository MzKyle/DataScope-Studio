# C2b production typed storage

Status: succeeded

| Backend | Catalog MB | Peak RSS MB | Prepare s |
| --- | ---: | ---: | ---: |
| eav | 2478.957 | 591.577 | 0.000 |
| typed_time | 115.220 | 377.717 | 52.272 |
| typed_none | 101.753 | 377.311 | 44.862 |

| Query | EAV P50/P95 ms | Typed time P50/P95 ms | Typed none P50/P95 ms |
| --- | ---: | ---: | ---: |
| find_errors | 4770.73 / 5631.91 | 2555.55 / 2672.61 | 2178.03 / 2277.41 |
| low_battery | 12688.15 / 13585.22 | 4342.18 / 4773.92 | 3301.85 / 3880.91 |
| state_duration | 5966.24 / 6646.06 | 2983.97 / 3365.99 | 3026.71 / 3389.61 |
| custom_scalar_key | 10266.06 / 10838.35 | 19.48 / 25.89 | 263.88 / 324.06 |
| custom_time_range | 2817.40 / 3109.98 | 12.19 / 13.02 | 5232.96 / 5590.94 |
| custom_numeric_threshold | 11181.88 / 11629.14 | 5227.29 / 5676.98 | 5369.58 / 5559.21 |
| compare | 27299.39 / 28903.14 | 11097.60 / 11570.04 | 12409.35 / 12918.45 |

Acceptance: `{"gates": {"typed_rows_at_most_two_per_sample": true, "writer_counts_match_sql": true, "all_values_retained": true, "no_eav_fallback": true, "storage_at_most_2x_csv": true, "storage_reduced_at_least_80_percent": true}, "storage_amplification": 1.2130282949409688, "storage_reduction": 0.9535205728882676, "query_latency_gates": "not a C2b storage acceptance condition"}`

Raw JSON includes every timing sample, SQL/EXPLAIN, untimed counts, source/code hashes and storage objects.
This measures index construction and compatibility queries, not Rerun build or Diagnostics performance.
