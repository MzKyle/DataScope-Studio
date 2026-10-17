# Query storage benchmark: benchmark_20261006_033145_baseline_matrix_fixed_case_C_2308be75

Date: 2026-10-06T03:31:45.229131+00:00. Mode: **full**. Status: succeeded.

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
| Source rows | 10,000.000 |
| Frequency (Hz) | 1,000.000 |
| Duration (s) | 10.000 |
| Telemetry scalars / states | 30 / 1 |
| Primary query rows | 320,000.000 |
| Row amplification | 32.000 |
| Source size (MB) | 3.132 |
| SQLite size before peer (MB) | 82.305 |
| Storage amplification | 26.282 |
| RRD size (MB) | 25.442 |
| RBL size (MB) | 0.034 |
| Sampled peak RSS (MB) | 436.031 |
| OS lifetime peak RSS (MB) | 436.031 |
| RSS before / after (MB) | 97.362 / 177.066 |

The SQLite/source ratio includes metadata and three indexes for the primary recording;
it is measured before adding the bounded comparison peer. MB/GB use decimal units.
`scalar_fields` includes the ten base telemetry fields, excludes numeric `error_code`.

## Pipeline

| Stage | ms |
| --- | ---: |
| Dataset generation | 125.647 |
| import_ms | 11.211 |
| schema_profile_ms | 2,354.883 |
| inspect_total_ms | 2,418.695 |
| inspect_ms | 63.812 |
| mapping_suggest_ms | 17.626 |
| mapping_validate_ms | 16.360 |
| mapping_save_ms | 59.371 |
| rerun_convert_ms | 52,359.942 |
| rerun_cleanup_ms | 1.893 |
| blueprint_ms | 19.013 |
| query_insert_ms | 3,770.209 |
| query_index_ms | 8,774.090 |
| recording_build_ms | 61,391.447 |
| rerun_artifact_ms | 52,380.848 |
| recording_other_ms | 236.509 |

`inspect_ms` excludes the nested schema-profile call; `inspect_total_ms` includes it.
`query_insert_ms` times executemany only; `query_index_ms` also includes CSV parsing,
row expansion, JSON serialization, delete and transaction commit.

## Query performance

| Query | Result rows | min | mean | P50 | P95 | max (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| find_errors | 1000 | 201.120 | 227.878 | 212.829 | 297.689 | 297.689 |
| low_battery | 1000 | 405.020 | 434.532 | 409.929 | 487.190 | 487.190 |
| state_duration | 1000 | 141.490 | 183.650 | 186.507 | 235.871 | 235.871 |
| custom_scalar_key | 1000 | 2,408.423 | 2,755.550 | 2,783.795 | 3,061.681 | 3,061.681 |
| custom_time_range | 352 | 6,340.265 | 6,434.684 | 6,442.058 | 6,541.323 | 6,541.323 |
| custom_numeric_threshold | 556 | 5,944.026 | 6,594.878 | 6,684.393 | 7,557.440 | 7,557.440 |
| compare | 4 | 1,253.513 | 1,592.607 | 1,663.663 | 1,776.627 | 1,776.627 |
| diagnostics | 1000 | 7,234.617 | 8,687.582 | 7,530.396 | 10,778.595 | 10,778.595 |
| time_sync_csv | 0 | 83.950 | 110.027 | 111.410 | 135.536 | 135.536 |
| time_sync | 1 | 2.745 | 4.434 | 4.604 | 5.567 | 5.567 |

Warm-ups: 1; measured repetitions: 5; result limit: 1000.
P95 uses nearest rank; with five runs it is the maximum, not a robust tail estimate.
Query timing includes production SQLite reads/sorts and Python processing; validation is excluded.
time_sync uses two real inspected MCAP topics (four metadata query rows); no auxiliary RRD build.
Current MCAP inspection supplies shared file-wide ranges, so the generated 20 ms topic offset
produces zero reported deltas. This is metadata-query latency, not sensor-sync accuracy.
time_sync_csv is the expected empty CSV path. Neither measures synchronization of scalar samples.
Compare uses battery/temperature across 10000 + 1000 source samples.
Queries run after ingestion and warm-up with a warm OS cache; no cold-cache claim.

## Memory by phase

| Phase | RSS before | RSS after | Sampled peak (MB) |
| --- | ---: | ---: | ---: |
| dataset_generation | 97.468 | 97.501 | 97.501 |
| primary/import | 99.062 | 99.770 | 100.438 |
| primary/inspect | 99.770 | 102.658 | 112.959 |
| primary/mapping | 102.658 | 101.442 | 102.719 |
| primary/recording_build | 101.442 | 138.879 | 150.581 |
| peer/import | 133.181 | 134.021 | 134.021 |
| peer/inspect | 134.021 | 136.528 | 140.567 |
| peer/mapping | 136.528 | 136.888 | 136.888 |
| peer/recording_build | 136.888 | 139.919 | 143.856 |
| query/find_errors | 132.784 | 146.043 | 147.227 |
| query/low_battery | 146.043 | 134.877 | 161.096 |
| query/state_duration | 134.877 | 144.921 | 152.347 |
| query/time_sync | 144.921 | 157.565 | 157.565 |
| query/custom_scalar_key | 157.565 | 158.650 | 162.472 |
| query/custom_time_range | 158.650 | 172.155 | 174.166 |
| query/custom_numeric_threshold | 172.155 | 171.880 | 175.940 |
| query/compare | 171.880 | 168.931 | 176.280 |
| query/diagnostics | 168.931 | 177.934 | 436.031 |
| time_sync_fixture/build | 177.000 | 177.070 | 177.070 |
| query/time_sync_topics | 177.070 | 177.070 | 177.070 |

## Correctness and retained artifacts

Exact primary/peer index cardinalities, recording success and nonempty artifacts (full mode),
error/state/battery values, adjacent durations, numeric/key/time filters, compare aggregates
and stable result hashes are checked. Isolated index variants must return identical results.

- Retained dataset: none
- Retained workspace: none
