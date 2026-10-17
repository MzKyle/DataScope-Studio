# Query storage benchmark: benchmark_20261006_031650_baseline_smoke_fixed_c509c566

Date: 2026-10-06T03:16:50.976448+00:00. Mode: **full**. Status: succeeded.

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
| Source rows | 30,000.000 |
| Frequency (Hz) | 200.000 |
| Duration (s) | 150.000 |
| Telemetry scalars / states | 30 / 1 |
| Primary query rows | 960,000.000 |
| Row amplification | 32.000 |
| Source size (MB) | 9.446 |
| SQLite size before peer (MB) | 246.792 |
| Storage amplification | 26.127 |
| RRD size (MB) | 84.227 |
| RBL size (MB) | 0.034 |
| Sampled peak RSS (MB) | 934.932 |
| OS lifetime peak RSS (MB) | 934.961 |
| RSS before / after (MB) | 97.624 / 207.155 |

The SQLite/source ratio includes metadata and three indexes for the primary recording;
it is measured before adding the bounded comparison peer. MB/GB use decimal units.
`scalar_fields` includes the ten base telemetry fields, excludes numeric `error_code`.

## Pipeline

| Stage | ms |
| --- | ---: |
| Dataset generation | 386.781 |
| import_ms | 16.750 |
| schema_profile_ms | 3,440.460 |
| inspect_total_ms | 3,537.194 |
| inspect_ms | 96.733 |
| mapping_suggest_ms | 11.467 |
| mapping_validate_ms | 15.196 |
| mapping_save_ms | 32.757 |
| rerun_convert_ms | 187,500.423 |
| rerun_cleanup_ms | 0.585 |
| blueprint_ms | 14.861 |
| query_insert_ms | 15,531.244 |
| query_index_ms | 35,005.691 |
| recording_build_ms | 222,679.520 |
| rerun_artifact_ms | 187,515.870 |
| recording_other_ms | 157.959 |

`inspect_ms` excludes the nested schema-profile call; `inspect_total_ms` includes it.
`query_insert_ms` times executemany only; `query_index_ms` also includes CSV parsing,
row expansion, JSON serialization, delete and transaction commit.

## Query performance

| Query | Result rows | min | mean | P50 | P95 | max (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| find_errors | 1000 | 434.740 | 511.253 | 486.645 | 654.914 | 654.914 |
| low_battery | 1000 | 1,544.141 | 1,651.765 | 1,672.640 | 1,759.723 | 1,759.723 |
| state_duration | 1000 | 495.591 | 579.632 | 580.455 | 718.611 | 718.611 |
| custom_scalar_key | 1000 | 5,769.159 | 6,560.472 | 6,912.476 | 7,011.658 | 7,011.658 |
| custom_time_range | 352 | 16,069.710 | 17,151.143 | 17,396.735 | 17,994.574 | 17,994.574 |
| custom_numeric_threshold | 1000 | 15,438.574 | 17,302.809 | 17,106.352 | 18,608.619 | 18,608.619 |
| compare | 4 | 2,434.991 | 2,992.610 | 3,018.905 | 3,420.036 | 3,420.036 |
| compare_all | 64 | 22,880.095 | 26,675.449 | 24,460.850 | 31,639.961 | 31,639.961 |
| diagnostics | 1000 | 21,300.669 | 22,699.004 | 23,033.312 | 23,668.411 | 23,668.411 |
| time_sync_csv | 0 | 245.475 | 305.446 | 293.282 | 358.969 | 358.969 |
| time_sync | 1 | 10.052 | 10.778 | 10.518 | 12.118 | 12.118 |

Warm-ups: 1; measured repetitions: 5; result limit: 1000.
P95 uses nearest rank; with five runs it is the maximum, not a robust tail estimate.
Query timing includes production SQLite reads/sorts and Python processing; validation is excluded.
time_sync uses two real inspected MCAP topics (four metadata query rows); no auxiliary RRD build.
Current MCAP inspection supplies shared file-wide ranges, so the generated 20 ms topic offset
produces zero reported deltas. This is metadata-query latency, not sensor-sync accuracy.
time_sync_csv is the expected empty CSV path. Neither measures synchronization of scalar samples.
Compare uses battery/temperature across 30000 + 1000 source samples.
Queries run after ingestion and warm-up with a warm OS cache; no cold-cache claim.

## Memory by phase

| Phase | RSS before | RSS after | Sampled peak (MB) |
| --- | ---: | ---: | ---: |
| dataset_generation | 97.731 | 97.759 | 97.759 |
| primary/import | 99.242 | 99.930 | 101.761 |
| primary/inspect | 99.930 | 103.559 | 121.147 |
| primary/mapping | 103.559 | 103.809 | 103.809 |
| primary/recording_build | 103.809 | 141.275 | 187.757 |
| peer/import | 134.398 | 135.156 | 135.156 |
| peer/inspect | 135.156 | 137.826 | 142.782 |
| peer/mapping | 137.826 | 138.088 | 138.088 |
| peer/recording_build | 138.088 | 134.689 | 144.433 |
| query/find_errors | 133.235 | 147.042 | 149.090 |
| query/low_battery | 147.042 | 144.814 | 162.501 |
| query/state_duration | 144.814 | 156.574 | 178.729 |
| query/time_sync | 155.525 | 160.285 | 160.285 |
| query/custom_scalar_key | 160.285 | 156.762 | 164.987 |
| query/custom_time_range | 156.762 | 165.503 | 167.576 |
| query/custom_numeric_threshold | 165.503 | 165.847 | 169.173 |
| query/compare | 165.847 | 173.801 | 200.016 |
| query/compare_all | 173.801 | 204.669 | 924.598 |
| query/diagnostics | 204.669 | 207.008 | 934.932 |
| time_sync_fixture/build | 207.122 | 207.159 | 207.159 |
| query/time_sync_topics | 207.159 | 207.159 | 207.159 |

## Correctness and retained artifacts

Exact primary/peer index cardinalities, recording success and nonempty artifacts (full mode),
error/state/battery values, adjacent durations, numeric/key/time filters, compare aggregates
and stable result hashes are checked. Isolated index variants must return identical results.

- Retained dataset: D:\Programme\DataScope-Studio\benchmarks\results\.work\benchmark_20261006_031650_baseline_smoke_fixed_c509c566\robot.csv
- Retained workspace: D:\Programme\DataScope-Studio\benchmarks\results\.work\benchmark_20261006_031650_baseline_smoke_fixed_c509c566\workspace
