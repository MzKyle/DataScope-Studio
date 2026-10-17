# 2026-10-06 Query Storage baseline

成功运行的原始 JSON/Markdown 副本；独立索引实验单独提取其有效结果。
保留 run ID、环境、源码 commit、benchmark-code hash、source checksum 和每次 latency sample。
Git 仅保存报告，没有生成的 CSV、SQLite、RRD/RBL、DuckDB 或 Parquet。
分析见 [architecture benchmark](../../../../docs/architecture/query-storage-benchmark.md)
及 [ADR-001](../../../../docs/architecture/adr/ADR-001-query-storage.md)。

## Runs

| Baseline | JSON | Markdown | Scope |
| --- | --- | --- | --- |
| Smoke | [smoke.json](smoke.json) | [smoke.md](smoke.md) | full production build; 30k source / 960k query rows; diagnostics, two-metric + all-field compare |
| Matrix A | [matrix_a.json](matrix_a.json) | [matrix_a.md](matrix_a.md) | 10 s, 50 Hz, 10 telemetry scalars; full build |
| Matrix B | [matrix_b.json](matrix_b.json) | [matrix_b.md](matrix_b.md) | 10 s, 200 Hz, 30 telemetry scalars; full build |
| Matrix C | [matrix_c.json](matrix_c.json) | [matrix_c.md](matrix_c.md) | 10 s, 1000 Hz, 30 telemetry scalars; full build |
| Matrix D | [matrix_d.json](matrix_d.json) | [matrix_d.md](matrix_d.md) | 10 s, 200 Hz, 100 telemetry scalars; full build |
| Small index | [small_index.json](small_index.json) | [small_index.md](small_index.md) | 300k source / 9.6m query rows; index-only; no RRD/RBL, diagnostics or all-field compare |
| Smoke PoC | [duckdb_smoke.json](duckdb_smoke.json) | [duckdb_smoke.md](duckdb_smoke.md) | exact Smoke source checksum; read-only production golden; SQLite SQL pushdown / typed DuckDB / Parquet |
| Isolated indexes | [index_experiment.json](index_experiment.json) | [index_experiment.md](index_experiment.md) | extracted unaffected 320k-row experiment, separate fresh SQLite catalogs; excludes early pipeline/RSS |

一次 warm-up，通常五次正式查询；Small index 为三次。Nearest-rank P95 在这些次数下为最大值。
每个 sample 有声明 scalars + 一个 state + numeric error_code，timestamp 不展开为 value row。
Compare 第二条真实 Recording 至多 1000 samples，未测试两条等规模大 Recording。

## Commands

在仓库根目录使用同一 Python 环境顺序执行；重跑时结果路径有不同的 UTC 时间与随机 ID。

```bash
python benchmarks/run_benchmark.py --preset small --pipeline index-only --skip-diagnostics --skip-index-comparison --query-runs 3 --keep-dataset --keep-workspace --label baseline_small_index_fixed
python benchmarks/run_benchmark.py --preset smoke --label baseline_smoke_fixed --keep-dataset --keep-workspace --compare-all --skip-index-comparison
python benchmarks/run_benchmark.py --matrix --matrix-duration 10 --skip-index-comparison --label baseline_matrix_fixed
python benchmarks/duckdb_poc.py --baseline benchmarks/results/benchmark_20261006_031650_baseline_smoke_fixed_c509c566.json
```

PoC 要求成功且保留 dataset/workspace 的 baseline，重跑时替换其路径。
Medium/Large 仅提供预设，本轮未执行。Small 的 index-only 模式不是完整 Recording build。
独立索引实验来自早期 `--preset smoke --label baseline_smoke --keep-dataset --keep-workspace --compare-all` 的默认索引对照。
重新生成它时去掉 `--skip-index-comparison`；最终完整 Smoke 的 pipeline/RSS 使用修正后的独立重测。

## Provenance and limits

Production commit 为 `3b3840bd3e7dd66c90bcfdadfb8704158a2fdfac`。
Windows / i9-13900HX / 16.907 GB RAM / Python 3.11.5 / SQLite 3.42.0；其他版本见 JSON。
Benchmark 代码在测量过程中补充 CPU 名称、MCAP coverage 和 parallel aggregate validation；各报告保存实际 code hash。
最终 Smoke/矩阵/Small 的 time_sync 测试两个真实 MCAP topic 的 metadata Query，time_sync_csv 另记 CSV 空路径。
Fixture 有已知 20 ms offset，当前 shared file-wide range 导致零 delta，不能声称正确检测到了 offset。
早期 INSERT timing Mock 保留 batch 参数、抬高 build RSS，已改为 direct callable wrapper 并增加 batch-release regression。
受影响的完整 pipeline/RSS 结果重测；最终矩阵/PoC/Small/Smoke 与验证测试顺序独立执行。
Isolated indexes 来自早期不受影响的直接 SQL 实验，仅提取其数据，排除原 pipeline/RSS。
Warm caches、主机背景负载、不同物理布局、固定 engine 顺序限制结论。
SQLite Catalog 包含 metadata + indexes，PoC 文件仅含 typed samples / views，没有 Source 或 Rerun artifacts。
PoC RSS 包含生产 correctness reference，未覆盖 diagnostics parity。

原始报告中的 keep 路径是测量时的保留状态。
完成验证后尝试清理本轮保留文件，但自动审批检查拒绝了已核实目录的递归删除（`blocked by policy`）。
因此本机 `benchmarks/results/.work/` 中仍保留五个本轮运行目录（共 6,046,914,501 bytes，约 6.05 GB）；它们已被 Git 忽略，不属于交付报告。
恢复清理权限后只清理这些已核实的 run ID，保留这里的 JSON/Markdown。

```text
benchmark_20261006_015530_selfcheck_ce2f8611
benchmark_20261006_015545_baseline_smoke_41538061
benchmark_20261006_022940_baseline_small_index_e0812417
benchmark_20261006_024955_baseline_small_index_fixed_295b46c4
benchmark_20261006_031650_baseline_smoke_fixed_c509c566
```
Curated 报告保留测量时记录，不承诺绝对主机路径长期存在。
Failed/self-check runs 不在本 baseline 集合，不能由这些成功样本推出 SQLite 硬上限。

## Validation

| Command | Result |
| --- | --- |
| `python -m pytest -q` | 211 passed, 5 skipped (current rerun, 79.53 s) |
| `python -m pytest -q` in clean detached baseline | 211 passed, 5 skipped (86.26 s) |
| `python -m pytest -q benchmarks/test_benchmark.py` | 9 passed (final rerun, 19.32 s), including optional DuckDB parity and batch-release regression |
| `cd apps/desktop && npm test` | 14 files / 69 tests passed |
| `cd apps/desktop && npm run build` | TypeScript + Vite build passed |
| `python packaging/release/sanity_check.py` | passed |
| `cd apps/desktop/src-tauri && cargo check --locked` | attempted; cargo unavailable, check not executed |

首轮 Python 全量有两条 MCAP/ROS2 CLI failure，随后 targeted、clean baseline 和 current full rerun 通过。
没有改动生产实现或现有 tests；没有定位最初 failure 的原因。
Opt-in harness 使用极小真实 pipelines，检查准确行数、Query、索引等价、keep flags、异常清理、PoC parity/checksum 与 Catalog 只读。
