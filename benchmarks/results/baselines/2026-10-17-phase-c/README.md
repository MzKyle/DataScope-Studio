# Phase C：Query Storage Architecture Decision Validation

最终查询测量日期：2026-10-17，Windows / i9-13900HX / Python 3.11.5。
本目录保留原始 JSON/Markdown，不包含生成的 CSV、SQLite、DuckDB、Parquet 或 RRD/RBL。
[架构分析](../../../../docs/architecture/query-storage-phase-c.md)、[ADR-001](../../../../docs/architecture/adr/ADR-001-query-storage.md)、
[运行说明](../../../README.md)包含方法、决策和限制。

**Decision: A. Keep optimized SQLite.** Covering variant 的七类 Query 在 Smoke/Small/Medium 全部达到 P95 ≤ 1 秒；Medium 最慢为 compare 537.74 ms。
生产仍使用现有 EAV；Diagnostics 5 秒 gate 和完整 semantic/lifecycle/packaging parity 仍待下一阶段验证。

## Evidence

| Study | JSON | Markdown | Scope |
| --- | --- | --- | --- |
| Smoke | [smoke.json](smoke.json) | [smoke.md](smoke.md) | 30,000 primary + 1,000 peer samples；七组配置；实际生产七类 Query 校验；独立执行路径 ablations |
| Small | [small.json](small.json) | [small.md](small.md) | 300,000 + 1,000 samples；七组配置；实际生产七类 Query 校验 |
| Medium | [medium.json](medium.json) | [medium.md](medium.md) | 3,000,000 + 1,000 samples；96,032,000 logical values；七组配置；独立 CSV oracle |
| Interrupted October 7 | [interrupted_medium_2026-10-07.json](interrupted_medium_2026-10-07.json) | [interrupted_medium_2026-10-07.md](interrupted_medium_2026-10-07.md) | 原始 partial report 的逐字节副本；原 status=running 是中断时快照，不代表仍有进程；不纳入最终 Query 表 |
| Before constant-sort correction | [order_alias_medium_control.json](order_alias_medium_control.json) | [order_alias_medium_control.md](order_alias_medium_control.md) | 完整旧轮；typed scalar-key 因排序/索引选择回退，修正后重测；其中未变化的 EAV 控制按严格条件复用 |
| Interrupted Smoke control | [interrupted_smoke_control.json](interrupted_smoke_control.json) | [interrupted_smoke_control.md](interrupted_smoke_control.md) | 修正公共 typed SQL 前启动的 Smoke，补充生产 ablation 未完成时停止；保留原快照，不纳入最终表 |

每类 Query 一次 warm-up + 五次正式运行，limit=1000，nearest-rank P95 为最大样本。
所有 backend 保留所有 numeric/state fields；compare 对 battery/temperature 聚合两个 Recording 的全部样本。
Typed SQLite 的 none/time/minimal/covering 四组，加 Legacy EAV SQL pushdown、DuckDB table 和 DuckDB querying Parquet，共七组。
Legacy EAV 是优化 SQL 下推控制；生产 Python filtering 的历史延迟另列，不能混作同一条执行路径。

## Reproduction

从没有 retained artifacts 的干净 checkout 重跑：

```bash
python -m pip install -r benchmarks/requirements-duckdb.txt
python benchmarks/backend_comparison.py --preset smoke --production-control
python benchmarks/backend_comparison.py --preset small
python benchmarks/backend_comparison.py --preset medium
```

本轮实际命令（依赖本机仍保留的原数据）：

```bash
python benchmarks/backend_comparison.py --resume-from benchmarks/results/benchmark_phase_c_20261007_145014_b79b78cf.json --reuse-legacy-control benchmarks/results/benchmark_phase_c_20261017_014856_967c1c94.json
python benchmarks/backend_comparison.py --baseline benchmarks/results/baselines/2026-10-06/smoke.json --production-control
python benchmarks/backend_comparison.py --baseline benchmarks/results/baselines/2026-10-06/small_index.json
```

归档结果中的绝对路径只描述测量时的 artifacts，不承诺 Git checkout 有这些大文件。
Phase A/B 的全部结果保持原字节；恢复运行也没有重写或删除 October 7 的 source run。

## Provenance and limits

Medium 的 Legacy EAV / Typed none / Typed time 已于 October 7 完成 preparation；October 17 只读复用这些数据库。
输入 SHA256、数据库大小、recording/field/state dictionaries、physical counts 和依赖版本均先校验；最终所有 Query 在 October 17 新进程中重测。
修正 typed-only 排序后，typed Query 全部重测；同日已完成的 EAV 控制仅在 SQL/oracle/source/policy/runtime 完全匹配时保留原实测样本，并记录原环境/code hash。
复用的 build 时间、code hash 和 RSS 保留原日期；它们不能当作与 October 17 新建 backends 同时发生的吞吐率对决。
Workflow RSS 对复用条目取原 build-stage peak 与新 query-worker peak 的较大值；JSON 保留两者。
Fresh backend 的 RSS 包括其自身 prepare/query；全部都不含 parent CSV oracle 或其他 backend 的分配。

所有 durable size 都包含 samples + dictionaries，排除 CSV、生产 metadata 和 Rerun artifacts。
SQLite WAL checkpoint、DuckDB CHECKPOINT 和 Parquet 文件写完后测大小；size 不是构建时 transient disk peak。
SQLite cache 64 MiB / temp file，DuckDB 四线程 / 1 GB engine limit；不同资源设置、缓存与物理存储仍限制因果解释。
Warm filesystem cache、固定顺序、单机、单用户、合成平滑非 null CSV；没有 cold-cache 或并发容量结论。
Loader 也不同：SQLite 一遍 Python CSV + executemany；DuckDB numeric/state 分别读取两次 native CSV。
SQL INSERT 子计时与 load 总计时单列，不能把全部导入差距归因于引擎 INSERT。

独立 BIGINT result channel 修复了 mixed UNION 潜在的 2^53 以上整数精度损失；回归覆盖 SQLite/table/Parquet。
October 7 partial 只覆盖 error_code 0/42，原样保留。time_sync offset 仍是已知正确性缺口；diagnostics 新后端 parity/5 秒预算尚未验证。
Null/mixed/schema evolution、CV/ROS、通用 text log、删除/恢复、并发、完整 packaging 以及完整 Rerun build 均不在通过结论内。

## Validation

- 三档成功、21 个 backend results、147 组 Query latency distributions；每组五次正式运行全部通过 canonical parity。
- Smoke/Small 的独立 CSV oracle 另外通过实际生产 Workspace 七类 Query 对照；Medium 使用同一 oracle。
- 每份 JSON 保存 source SHA256、code hash、依赖、SQL/EXPLAIN、raw timings、行数、build/storage/RSS 和 cleanup 状态。
- 当前代码 fingerprint 与最终三份报告一致；仅复用的 Medium EAV 控制保留原 code hash，并与归档控制的 SQL/原始样本严格相等。
- 2026-10-06 全部基线文件经过逐字节 SHA256 校验，未被覆盖。

| Command | Result / date |
| --- | --- |
| `python -m pytest -q` | 211 passed, 5 skipped / 2026-10-17 |
| `python -m pytest -q benchmarks/test_benchmark.py` | 17 passed / 2026-10-17；包含四索引、SQL plan/parity、BIGINT、恢复链、未变化控制复用与失败清理 |
| `python -m compileall -q benchmarks` | Passed / 2026-10-17 |
| `python packaging/release/sanity_check.py` | Passed / 2026-10-17 |
| `git diff --check` | Passed / 2026-10-17 |
| `cd apps/desktop; npm test` | 14 files, 69 tests passed / 2026-10-07，Desktop 无修改 |
| `cd apps/desktop; npm run build` | tsc + Vite build passed / 2026-10-07，Desktop 无修改 |

10 月 7 日全量 pytest 曾出现 ROS2 CLI fake_run 不接受 stdout：干净 HEAD 也复现、单独运行通过；10 月 17 日全量普通复跑通过。
没有修改生产代码/原有 tests 来绕过此波动。当前环境未安装 cargo，没有声称 Rust/Tauri 或完整 packaged runtime 验证通过。

## Retained artifacts / manual cleanup

此前自动审批审查已拒绝旧 artifacts 删除（blocked by policy）。本轮未绕过或重试旧目录删除；以下文件仍在 Git ignore 的 `.work/` 中。
正式新运行已各自清理其独占目录；历史输入及中断目录由人工在确认不再恢复运行后处理。
精确路径/字节数见 [retained-artifacts.json](retained-artifacts.json)。

| Directory under benchmarks/results/.work | Bytes |
| --- | ---: |
| `benchmark_20261006_015530_selfcheck_ce2f8611` | 879615 |
| `benchmark_20261006_015545_baseline_smoke_41538061` | 346607132 |
| `benchmark_20261006_022940_baseline_small_index_e0812417` | 2668984146 |
| `benchmark_20261006_024955_baseline_small_index_fixed_295b46c4` | 2668671963 |
| `benchmark_20261006_031650_baseline_smoke_fixed_c509c566` | 361804413 |
| `benchmark_phase_c_20261007_143434_75780e48` | 180091 |
| `benchmark_phase_c_20261007_145014_b79b78cf` | 27735713511 |
| `benchmark_phase_c_20261017_020703_29cfbc6b` | 298136352 |
| **Total** | **34080977223** |

人工清理建议：先确认下列绝对路径与表格一致，再逐个执行同样的命令；不要删除整个 `.work/` 或使用通配符。以下仅为建议，本轮没有执行：

```powershell
$benchmarkRun = Resolve-Path -LiteralPath 'D:\Programme\DataScope-Studio\benchmarks\results\.work\benchmark_20261006_015530_selfcheck_ce2f8611'
$benchmarkRun.Path
Get-Item -LiteralPath $benchmarkRun.Path
Remove-Item -LiteralPath $benchmarkRun.Path -Recurse
```
