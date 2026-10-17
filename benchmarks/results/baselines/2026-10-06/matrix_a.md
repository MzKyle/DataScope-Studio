# Query storage benchmark: benchmark_20261006_033037_baseline_matrix_fixed_case_A_1c06bfa5

Date: 2026-10-06T03:30:37.291951+00:00. Mode: **full**. Status: succeeded.

## Environment

- Platform: Windows-10-10.0.26300-SP0
- CPU: 13th Gen Intel(R) Core(TM) i9-13900HX
- Python: 3.11.5 (tags/v3.11.5:cce6ba9, Aug 24 2023, 14:38:34) [MSC v.1936 64 bit (AMD64)]
- RAM: 16.907 GB
- Commit: `3b3840bd3e7dd66c90bcfdadfb8704158a2fdfac`; dirty: True
- Benchmark code SHA256: `f6b226409d3dcd56718c24cbf2b249948fb247a0d0071946f6b71dbde80da175`

## Dataset and storage

| Metric | Value |
| --- | ---: |
| Source rows | 500.000 |
| Frequency (Hz) | 50.000 |
| Duration (s) | 10.000 |
| Telemetry scalars / states | 10 / 1 |
| Primary query rows | 6,000.000 |
| Row amplification | 12.000 |
| Source size (MB) | 0.058 |
| SQLite size before peer (MB) | 1.757 |
| Storage amplification | 30.455 |
| RRD size (MB) | 0.292 |
| RBL size (MB) | 0.034 |
| Sampled peak RSS (MB) | 158.630 |
| OS lifetime peak RSS (MB) | 159.674 |
| RSS before / after (MB) | 97.456 / 147.317 |

The SQLite/source ratio includes metadata and three indexes for the primary recording;
it is measured before adding the bounded comparison peer. MB/GB use decimal units.
`scalar_fields` includes the ten base telemetry fields, excludes numeric `error_code`.

## Pipeline

| Stage | ms |
| --- | ---: |
| Dataset generation | 2.777 |
| import_ms | 7.201 |
| schema_profile_ms | 485.844 |
| inspect_total_ms | 510.143 |
| inspect_ms | 24.299 |
| mapping_suggest_ms | 3.618 |
| mapping_validate_ms | 2.153 |
| mapping_save_ms | 6.864 |
| rerun_convert_ms | 817.378 |
| rerun_cleanup_ms | 0.174 |
| blueprint_ms | 3.805 |
| query_insert_ms | 15.233 |
| query_index_ms | 56.210 |
| recording_build_ms | 935.263 |
| rerun_artifact_ms | 821.357 |
| recording_other_ms | 57.697 |

`inspect_ms` excludes the nested schema-profile call; `inspect_total_ms` includes it.
`query_insert_ms` times executemany only; `query_index_ms` also includes CSV parsing,
row expansion, JSON serialization, delete and transaction commit.

## Query performance

| Query | Result rows | min | mean | P50 | P95 | max (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| find_errors | 75 | 5.592 | 17.716 | 13.723 | 31.517 | 31.517 |
| low_battery | 84 | 26.868 | 32.327 | 32.678 | 36.909 | 36.909 |
| state_duration | 500 | 8.915 | 12.693 | 12.978 | 16.019 | 16.019 |
| custom_scalar_key | 500 | 58.965 | 83.473 | 63.709 | 130.885 | 130.885 |
| custom_time_range | 132 | 50.979 | 70.893 | 56.632 | 134.363 | 134.363 |
| custom_numeric_threshold | 28 | 45.682 | 60.622 | 55.110 | 85.353 | 85.353 |
| compare | 4 | 43.899 | 53.594 | 55.396 | 60.054 | 60.054 |
| diagnostics | 159 | 77.457 | 137.256 | 106.093 | 211.659 | 211.659 |
| time_sync_csv | 0 | 3.935 | 7.541 | 6.666 | 11.437 | 11.437 |
| time_sync | 1 | 3.510 | 8.617 | 11.056 | 12.758 | 12.758 |

Warm-ups: 1; measured repetitions: 5; result limit: 1000.
P95 uses nearest rank; with five runs it is the maximum, not a robust tail estimate.
Query timing includes production SQLite reads/sorts and Python processing; validation is excluded.
time_sync uses two real inspected MCAP topics (four metadata query rows); no auxiliary RRD build.
Current MCAP inspection supplies shared file-wide ranges, so the generated 20 ms topic offset
produces zero reported deltas. This is metadata-query latency, not sensor-sync accuracy.
time_sync_csv is the expected empty CSV path. Neither measures synchronization of scalar samples.
Compare uses battery/temperature across 500 + 500 source samples.
Queries run after ingestion and warm-up with a warm OS cache; no cold-cache claim.

## Memory by phase

| Phase | RSS before | RSS after | Sampled peak (MB) |
| --- | ---: | ---: | ---: |
| dataset_generation | 97.563 | 97.583 | 97.583 |
| primary/import | 99.115 | 99.828 | 99.828 |
| primary/inspect | 99.828 | 100.561 | 100.561 |
| primary/mapping | 100.561 | 102.498 | 102.498 |
| primary/recording_build | 102.498 | 136.311 | 141.418 |
| peer/import | 133.931 | 134.304 | 134.304 |
| peer/inspect | 134.304 | 134.988 | 134.988 |
| peer/mapping | 134.988 | 135.844 | 135.844 |
| peer/recording_build | 135.844 | 133.497 | 142.885 |
| query/find_errors | 130.568 | 136.487 | 136.487 |
| query/low_battery | 136.487 | 146.428 | 146.428 |
| query/state_duration | 146.428 | 130.675 | 147.337 |
| query/time_sync | 130.675 | 135.590 | 135.590 |
| query/custom_scalar_key | 135.590 | 137.314 | 144.359 |
| query/custom_time_range | 137.314 | 147.304 | 148.091 |
| query/custom_numeric_threshold | 147.304 | 157.471 | 158.208 |
| query/compare | 157.471 | 137.867 | 158.630 |
| query/diagnostics | 137.867 | 146.518 | 147.276 |
| time_sync_fixture/build | 146.633 | 147.325 | 147.325 |
| query/time_sync_topics | 147.325 | 147.341 | 147.341 |

## Correctness and retained artifacts

Exact primary/peer index cardinalities, recording success and nonempty artifacts (full mode),
error/state/battery values, adjacent durations, numeric/key/time filters, compare aggregates
and stable result hashes are checked. Isolated index variants must return identical results.

- Retained dataset: none
- Retained workspace: none
