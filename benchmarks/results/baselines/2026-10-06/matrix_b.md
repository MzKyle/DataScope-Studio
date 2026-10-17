# Query storage benchmark: benchmark_20261006_033045_baseline_matrix_fixed_case_B_784b7cea

Date: 2026-10-06T03:30:45.737393+00:00. Mode: **full**. Status: succeeded.

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
| Source rows | 2,000.000 |
| Frequency (Hz) | 200.000 |
| Duration (s) | 10.000 |
| Telemetry scalars / states | 30 / 1 |
| Primary query rows | 64,000.000 |
| Row amplification | 32.000 |
| Source size (MB) | 0.627 |
| SQLite size before peer (MB) | 16.593 |
| Storage amplification | 26.480 |
| RRD size (MB) | 5.185 |
| RBL size (MB) | 0.034 |
| Sampled peak RSS (MB) | 220.471 |
| OS lifetime peak RSS (MB) | 220.471 |
| RSS before / after (MB) | 97.407 / 188.420 |

The SQLite/source ratio includes metadata and three indexes for the primary recording;
it is measured before adding the bounded comparison peer. MB/GB use decimal units.
`scalar_fields` includes the ten base telemetry fields, excludes numeric `error_code`.

## Pipeline

| Stage | ms |
| --- | ---: |
| Dataset generation | 24.876 |
| import_ms | 8.407 |
| schema_profile_ms | 2,150.105 |
| inspect_total_ms | 2,185.652 |
| inspect_ms | 35.548 |
| mapping_suggest_ms | 13.263 |
| mapping_validate_ms | 10.846 |
| mapping_save_ms | 47.928 |
| rerun_convert_ms | 11,368.325 |
| rerun_cleanup_ms | 0.296 |
| blueprint_ms | 2.882 |
| query_insert_ms | 847.565 |
| query_index_ms | 1,911.581 |
| recording_build_ms | 13,454.097 |
| rerun_artifact_ms | 11,371.502 |
| recording_other_ms | 171.014 |

`inspect_ms` excludes the nested schema-profile call; `inspect_total_ms` includes it.
`query_insert_ms` times executemany only; `query_index_ms` also includes CSV parsing,
row expansion, JSON serialization, delete and transaction commit.

## Query performance

| Query | Result rows | min | mean | P50 | P95 | max (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| find_errors | 300 | 30.719 | 53.982 | 38.970 | 86.207 | 86.207 |
| low_battery | 334 | 69.127 | 80.027 | 73.746 | 98.081 | 98.081 |
| state_duration | 1000 | 25.786 | 33.601 | 28.996 | 55.306 | 55.306 |
| custom_scalar_key | 1000 | 572.493 | 684.414 | 707.400 | 766.291 | 766.291 |
| custom_time_range | 352 | 812.319 | 1,008.169 | 1,018.317 | 1,123.503 | 1,123.503 |
| custom_numeric_threshold | 112 | 856.173 | 1,041.213 | 1,057.932 | 1,228.922 | 1,228.922 |
| compare | 4 | 168.429 | 216.839 | 198.323 | 306.949 | 306.949 |
| diagnostics | 635 | 1,085.642 | 1,250.668 | 1,304.721 | 1,338.641 | 1,338.641 |
| time_sync_csv | 0 | 20.828 | 22.585 | 21.153 | 25.948 | 25.948 |
| time_sync | 1 | 2.581 | 2.904 | 2.870 | 3.260 | 3.260 |

Warm-ups: 1; measured repetitions: 5; result limit: 1000.
P95 uses nearest rank; with five runs it is the maximum, not a robust tail estimate.
Query timing includes production SQLite reads/sorts and Python processing; validation is excluded.
time_sync uses two real inspected MCAP topics (four metadata query rows); no auxiliary RRD build.
Current MCAP inspection supplies shared file-wide ranges, so the generated 20 ms topic offset
produces zero reported deltas. This is metadata-query latency, not sensor-sync accuracy.
time_sync_csv is the expected empty CSV path. Neither measures synchronization of scalar samples.
Compare uses battery/temperature across 2000 + 1000 source samples.
Queries run after ingestion and warm-up with a warm OS cache; no cold-cache claim.

## Memory by phase

| Phase | RSS before | RSS after | Sampled peak (MB) |
| --- | ---: | ---: | ---: |
| dataset_generation | 97.518 | 97.542 | 97.542 |
| primary/import | 98.931 | 99.930 | 99.930 |
| primary/inspect | 99.930 | 101.851 | 101.851 |
| primary/mapping | 101.851 | 101.351 | 102.289 |
| primary/recording_build | 101.351 | 133.448 | 139.211 |
| peer/import | 131.473 | 131.785 | 131.785 |
| peer/inspect | 131.785 | 133.386 | 138.076 |
| peer/mapping | 133.386 | 129.196 | 133.804 |
| peer/recording_build | 129.196 | 134.631 | 142.893 |
| query/find_errors | 133.001 | 146.141 | 146.141 |
| query/low_battery | 146.141 | 160.838 | 160.838 |
| query/state_duration | 160.838 | 133.284 | 163.025 |
| query/time_sync | 133.284 | 147.018 | 147.018 |
| query/custom_scalar_key | 147.018 | 147.915 | 151.978 |
| query/custom_time_range | 147.915 | 161.800 | 163.852 |
| query/custom_numeric_threshold | 161.800 | 176.620 | 178.663 |
| query/compare | 176.620 | 148.427 | 179.286 |
| query/diagnostics | 148.427 | 187.998 | 220.471 |
| time_sync_fixture/build | 188.113 | 188.346 | 188.346 |
| query/time_sync_topics | 188.346 | 188.424 | 188.424 |

## Correctness and retained artifacts

Exact primary/peer index cardinalities, recording success and nonempty artifacts (full mode),
error/state/battery values, adjacent durations, numeric/key/time filters, compare aggregates
and stable result hashes are checked. Isolated index variants must return identical results.

- Retained dataset: none
- Retained workspace: none
