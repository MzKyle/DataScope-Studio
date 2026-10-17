# Query storage benchmark: benchmark_20261006_033548_baseline_matrix_fixed_case_D_8459f746

Date: 2026-10-06T03:35:48.912421+00:00. Mode: **full**. Status: succeeded.

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
| Telemetry scalars / states | 100 / 1 |
| Primary query rows | 204,000.000 |
| Row amplification | 102.000 |
| Source size (MB) | 2.027 |
| SQLite size before peer (MB) | 52.003 |
| Storage amplification | 25.650 |
| RRD size (MB) | 27.082 |
| RBL size (MB) | 0.034 |
| Sampled peak RSS (MB) | 325.296 |
| OS lifetime peak RSS (MB) | 325.296 |
| RSS before / after (MB) | 97.886 / 186.278 |

The SQLite/source ratio includes metadata and three indexes for the primary recording;
it is measured before adding the bounded comparison peer. MB/GB use decimal units.
`scalar_fields` includes the ten base telemetry fields, excludes numeric `error_code`.

## Pipeline

| Stage | ms |
| --- | ---: |
| Dataset generation | 76.797 |
| import_ms | 9.362 |
| schema_profile_ms | 20,625.102 |
| inspect_total_ms | 20,706.656 |
| inspect_ms | 81.554 |
| mapping_suggest_ms | 13.456 |
| mapping_validate_ms | 10.871 |
| mapping_save_ms | 111.271 |
| rerun_convert_ms | 24,952.440 |
| rerun_cleanup_ms | 1.962 |
| blueprint_ms | 6.724 |
| query_insert_ms | 3,527.164 |
| query_index_ms | 5,988.556 |
| recording_build_ms | 31,464.012 |
| rerun_artifact_ms | 24,961.127 |
| recording_other_ms | 514.329 |

`inspect_ms` excludes the nested schema-profile call; `inspect_total_ms` includes it.
`query_insert_ms` times executemany only; `query_index_ms` also includes CSV parsing,
row expansion, JSON serialization, delete and transaction commit.

## Query performance

| Query | Result rows | min | mean | P50 | P95 | max (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| find_errors | 300 | 25.889 | 33.733 | 28.383 | 54.892 | 54.892 |
| low_battery | 334 | 147.162 | 163.508 | 161.588 | 189.318 | 189.318 |
| state_duration | 1000 | 24.470 | 29.027 | 26.947 | 40.448 | 40.448 |
| custom_scalar_key | 1000 | 2,013.022 | 2,188.766 | 2,220.643 | 2,284.851 | 2,284.851 |
| custom_time_range | 1000 | 2,650.888 | 2,837.203 | 2,726.333 | 3,130.632 | 3,130.632 |
| custom_numeric_threshold | 112 | 2,763.737 | 2,865.253 | 2,881.602 | 2,938.092 | 2,938.092 |
| compare | 4 | 388.305 | 407.872 | 404.572 | 428.927 | 428.927 |
| diagnostics | 639 | 2,933.250 | 3,052.527 | 3,002.820 | 3,300.345 | 3,300.345 |
| time_sync_csv | 0 | 45.042 | 49.471 | 47.030 | 60.048 | 60.048 |
| time_sync | 1 | 2.751 | 3.135 | 3.245 | 3.509 | 3.509 |

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
| dataset_generation | 97.993 | 98.009 | 98.009 |
| primary/import | 99.394 | 100.196 | 100.196 |
| primary/inspect | 100.196 | 102.056 | 108.863 |
| primary/mapping | 102.056 | 102.654 | 103.055 |
| primary/recording_build | 102.654 | 135.098 | 155.390 |
| peer/import | 132.723 | 134.164 | 134.164 |
| peer/inspect | 134.164 | 135.041 | 141.275 |
| peer/mapping | 135.041 | 131.125 | 135.664 |
| peer/recording_build | 131.125 | 138.383 | 153.330 |
| query/find_errors | 135.717 | 148.394 | 148.394 |
| query/low_battery | 148.394 | 162.963 | 162.963 |
| query/state_duration | 162.963 | 137.183 | 165.454 |
| query/time_sync | 137.183 | 148.984 | 148.984 |
| query/custom_scalar_key | 148.984 | 150.041 | 153.739 |
| query/custom_time_range | 150.041 | 140.141 | 163.262 |
| query/custom_numeric_threshold | 140.141 | 154.079 | 156.156 |
| query/compare | 154.079 | 148.435 | 156.996 |
| query/diagnostics | 148.435 | 185.225 | 325.296 |
| time_sync_fixture/build | 185.340 | 186.274 | 186.274 |
| query/time_sync_topics | 186.274 | 186.282 | 186.282 |

## Correctness and retained artifacts

Exact primary/peer index cardinalities, recording success and nonempty artifacts (full mode),
error/state/battery values, adjacent durations, numeric/key/time filters, compare aggregates
and stable result hashes are checked. Isolated index variants must return identical results.

- Retained dataset: none
- Retained workspace: none
