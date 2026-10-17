# Query storage benchmark: benchmark_20261006_024955_baseline_small_index_fixed_295b46c4

Date: 2026-10-06T02:49:55.206406+00:00. Mode: **index-only**. Status: succeeded.

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
| Source rows | 300,000.000 |
| Frequency (Hz) | 200.000 |
| Duration (s) | 1,500.000 |
| Telemetry scalars / states | 30 / 1 |
| Primary query rows | 9,600,000.000 |
| Row amplification | 32.000 |
| Source size (MB) | 94.673 |
| SQLite size before peer (MB) | 2,470.486 |
| Storage amplification | 26.095 |
| RRD size (MB) | not measured |
| RBL size (MB) | not measured |
| Sampled peak RSS (MB) | 603.906 |
| OS lifetime peak RSS (MB) | 606.441 |
| RSS before / after (MB) | 98.132 / 140.009 |

The SQLite/source ratio includes metadata and three indexes for the primary recording;
it is measured before adding the bounded comparison peer. MB/GB use decimal units.
`scalar_fields` includes the ten base telemetry fields, excludes numeric `error_code`.

## Pipeline

| Stage | ms |
| --- | ---: |
| Dataset generation | 6,522.281 |
| import_ms | 239.453 |
| schema_profile_ms | 8,679.492 |
| inspect_total_ms | 10,087.704 |
| inspect_ms | 1,408.212 |
| mapping_suggest_ms | 7.928 |
| mapping_validate_ms | 7.105 |
| mapping_save_ms | 47.422 |
| query_insert_ms | 129,296.814 |
| query_index_ms | 281,445.685 |
| recording_build_ms | not measured |
| rerun_artifact_ms | not measured |
| recording_other_ms | not measured |

`inspect_ms` excludes the nested schema-profile call; `inspect_total_ms` includes it.
`query_insert_ms` times executemany only; `query_index_ms` also includes CSV parsing,
row expansion, JSON serialization, delete and transaction commit.

## Query performance

| Query | Result rows | min | mean | P50 | P95 | max (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| find_errors | 1000 | 5,010.306 | 5,258.181 | 5,252.337 | 5,511.899 | 5,511.899 |
| low_battery | 1000 | 17,045.831 | 18,228.088 | 18,465.420 | 19,173.012 | 19,173.012 |
| state_duration | 1000 | 7,084.931 | 7,365.109 | 7,300.275 | 7,710.120 | 7,710.120 |
| custom_scalar_key | 1000 | 58,370.059 | 65,303.612 | 62,037.408 | 75,503.370 | 75,503.370 |
| custom_time_range | 352 | 53,997.656 | 56,006.365 | 54,039.253 | 59,982.187 | 59,982.187 |
| custom_numeric_threshold | 1000 | 53,295.977 | 148,256.313 | 191,358.334 | 200,114.629 | 200,114.629 |
| compare | 4 | 26,003.441 | 26,701.057 | 26,700.569 | 27,399.160 | 27,399.160 |
| time_sync_csv | 0 | 3,093.544 | 3,181.308 | 3,099.525 | 3,350.855 | 3,350.855 |
| time_sync | 1 | 6.252 | 10.277 | 12.098 | 12.482 | 12.482 |

Warm-ups: 1; measured repetitions: 3; result limit: 1000.
P95 uses nearest rank; with five runs it is the maximum, not a robust tail estimate.
Query timing includes production SQLite reads/sorts and Python processing; validation is excluded.
time_sync uses two real inspected MCAP topics (four metadata query rows); no auxiliary RRD build.
Current MCAP inspection supplies shared file-wide ranges, so the generated 20 ms topic offset
produces zero reported deltas. This is metadata-query latency, not sensor-sync accuracy.
time_sync_csv is the expected empty CSV path. Neither measures synchronization of scalar samples.
Compare uses battery/temperature across 300000 + 1000 source samples.
Queries run after ingestion and warm-up with a warm OS cache; no cold-cache claim.

## Memory by phase

| Phase | RSS before | RSS after | Sampled peak (MB) |
| --- | ---: | ---: | ---: |
| dataset_generation | 98.238 | 98.255 | 98.255 |
| primary/import | 99.258 | 99.967 | 101.773 |
| primary/inspect | 99.967 | 103.010 | 175.460 |
| primary/mapping | 103.010 | 101.249 | 103.481 |
| primary/recording_build | 101.249 | 110.768 | 158.724 |
| peer/import | 109.126 | 109.974 | 109.974 |
| peer/inspect | 109.974 | 112.693 | 116.527 |
| peer/mapping | 112.693 | 109.179 | 113.095 |
| peer/recording_build | 109.179 | 113.627 | 113.648 |
| query/find_errors | 110.821 | 119.017 | 120.865 |
| query/low_battery | 119.017 | 126.599 | 128.496 |
| query/state_duration | 126.599 | 122.683 | 485.655 |
| query/time_sync | 121.635 | 125.768 | 125.768 |
| query/custom_scalar_key | 125.768 | 119.046 | 132.637 |
| query/custom_time_range | 119.046 | 129.241 | 131.133 |
| query/custom_numeric_threshold | 129.241 | 128.643 | 134.177 |
| query/compare | 128.643 | 139.809 | 603.906 |
| time_sync_fixture/build | 139.928 | 139.989 | 139.989 |
| query/time_sync_topics | 139.989 | 140.014 | 140.014 |

## Correctness and retained artifacts

Exact primary/peer index cardinalities, recording success and nonempty artifacts (full mode),
error/state/battery values, adjacent durations, numeric/key/time filters, compare aggregates
and stable result hashes are checked. Isolated index variants must return identical results.

- Retained dataset: D:\Programme\DataScope-Studio\benchmarks\results\.work\benchmark_20261006_024955_baseline_small_index_fixed_295b46c4\robot.csv
- Retained workspace: D:\Programme\DataScope-Studio\benchmarks\results\.work\benchmark_20261006_024955_baseline_small_index_fixed_295b46c4\workspace
