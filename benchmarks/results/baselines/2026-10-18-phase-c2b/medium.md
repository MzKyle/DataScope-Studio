# C2b production typed storage

Status: succeeded

| Backend | Catalog MB | Peak RSS MB | Prepare s |
| --- | ---: | ---: | ---: |
| typed_time | 1155.514 | 169.910 | 559.643 |

| Query | EAV P50/P95 ms | Typed time P50/P95 ms | Typed none P50/P95 ms |
| --- | ---: | ---: | ---: |
| find_errors | n/a | n/a | n/a |
| low_battery | n/a | n/a | n/a |
| state_duration | n/a | n/a | n/a |
| custom_scalar_key | n/a | n/a | n/a |
| custom_time_range | n/a | n/a | n/a |
| custom_numeric_threshold | n/a | n/a | n/a |
| compare | n/a | n/a | n/a |

Acceptance: `{"gates": {"typed_rows_at_most_two_per_sample": true, "writer_counts_match_sql": true, "all_values_retained": true, "no_eav_fallback": true, "storage_at_most_2x_csv": true, "storage_reduced_at_least_80_percent": true}, "storage_amplification": 1.2163571498677452, "storage_reduction": 0.9510583059298268, "query_latency_gates": "not a C2b storage acceptance condition"}`

Raw JSON includes every timing sample, SQL/EXPLAIN, untimed counts, source/code hashes and storage objects.
This measures index construction and compatibility queries, not Rerun build or Diagnostics performance.
