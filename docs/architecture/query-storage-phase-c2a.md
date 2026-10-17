# Phase C2a：生产 Custom Query 下推

本阶段将字段、路径、有限时间边界的筛选接入生产 `Workspace.custom_query()`。
现有 Recording 无需重建，API/CLI/Desktop 的请求和结果结构保持兼容。
数值与文本条件继续由原 `run_custom_query()` 执行；本阶段仍使用现有 EAV/JSON 数据和索引。

## Implementation and compatibility

内部 `CustomQueryPlan` 保存参数化 SQL 条件及 residual-filter 标志。计划仅供 Custom Query 使用，生产模块不导入 benchmarks。
模板、compare、Diagnostics、time_sync、Rerun、数据库 schema/version/indexes 和连接 PRAGMA 均未改造。

- `time_start`/`time_end` 为闭区间，有限数值编译为 `>=`/`<=`。非有限边界由原逻辑处理，避免改变 NaN/Infinity/null 的行为。
- key/path 保留 `.strip().lower()` 后的子串匹配。SQLite 的 ASCII lower 不等价于 Python Unicode lower，例如 Kelvin sign `K`；使用连接内 Python lower 函数和 SQL `instr()`。
- `%`、`_` 没有通配符含义，输入均使用 bound parameters。Unicode lower 的结果以最多 4096 项的连接内 LRU cache 保存，避免重复字段归一化且限制条目数量。
- 数值字符串、布尔值排除、contains/eq、text 和未知 operator 保留原函数的结果与惰性校验，无新增 JSON1 要求。
- 有 residual filter 时不下推 LIMIT；否则只对正整数 limit 下推。Core 非正/非整数 limit 的已有行为保留，API 的 1–10000 校验不变。
- 保留 `recording_id,time,entity_path,key` 四字段排序；现有 project/recording/semantic 限制原样组合。
- 数据库错误正常传播；没有捕获所有 SQL 错误后重试旧路径的机制。

这是执行路径优化，不减少持久化 EAV 行数或文件体积，也不提供 TypedSQLiteBackend。
默认启用安全下推，无用户设置和 migration；代码回滚即可恢复旧行为。

## Correctness verification

微型真实 SQLite fixtures 对照原函数和原 iterator（不传 query plan），检查 shape/type/order/value，包括 NaN 的专门比较。
覆盖 Unicode、组合过滤、字面特殊字符、null/重复时间、多 Recording、空 ID 列表、项目隔离、数值字符串、布尔值、大整数和非有限数值。
残余条件的首批候选不命中、未知 operator 的惰性报错、数据库错误及 schema/version 不变均有回归。
API 组合条件加 limit 的测试验证数值字符串与时间窗口；CLI/模板等既有集成测试继续运行。

## Performance protocol

`benchmarks/custom_query_pushdown.py` 只读已有 Smoke/Small Catalog 和输入 CSV。
Legacy worker 明确绕过 query plan，直接调用旧 iterator + 原 Python filter；pushdown worker 调用生产方法。
两者在独立进程中顺序运行，每类一次 warm-up、五次正式测量，limit=1000。
复用 generator/config、latency_stats、measure_query、MemorySampler、query_calls 和独立 generator-result validation，不重写原框架。

JSON 保存环境、生产/benchmark code hash、原始样本、P50/P95、结果 hash、RSS、实际 SQL 与 EXPLAIN。
三个查询均检查输出 hash 相同；预先和结束后检查 source/catalog SHA256、bytes、schema、version、cardinality 不变。
不执行 ANALYZE、不增加索引、不调整生产 cache/PRAGMA、不重新构建 Rerun，也不以原型的 sample-only SQL 替代生产入口。

读取/JSON 解码计数使用额外的非计时 pass，放在正式 RSS/latency 采样之后；不会将插桩成本计入延迟。
Fetched rows 指 SQLite iterator 已交给 Python 的行数，不是 SQLite engine 实际扫描行数。
晚时间窗口检查 fetched rows 等于输出窗口行数；低阈值查询仍可能遍历大量单字段候选，这是本阶段保留的成本。

验收门槛：Smoke 三类 Query P95 ≤ 1000 ms；Small 三类 Query 同轮 P95 至少提速 2 倍。
Nearest-rank P95 在五次测量时是最大样本，不能当作稳定生产 tail SLO。
固定顺序、warm filesystem cache、单机和合成数据仍限制外推；本阶段不执行 Medium/Large，也不替代 Diagnostics 的 5 秒门槛。

## Measured results: 2026-10-17

Smoke 30,000 / Small 300,000 primary samples，均为 200 Hz、32 个映射 value fields，使用原 Phase A Catalog。
两档全部通过既定性能门槛、精确输出 hash 和源文件/数据库只读校验。完整原始数据见
[C2a results](../../benchmarks/results/baselines/2026-10-17-phase-c2a/README.md)。

| Dataset / Query | Legacy P50 / P95 ms | Production P50 / P95 ms | P95 speedup | Fetched old / new | JSON decodes old / new |
| --- | ---: | ---: | ---: | ---: | ---: |
| smoke / custom_scalar_key | 2206.62 / 2268.77 | 306.76 / 313.86 | 7.23× | 30,976 / 1,000 | 30,976 / 1,000 |
| smoke / custom_time_range | 5238.17 / 5275.93 | 107.36 / 108.32 | 48.70× | 960,000 / 352 | 960,000 / 352 |
| smoke / custom_numeric_threshold | 5241.62 / 5267.80 | 415.55 / 418.26 | 12.59× | 909,293 / 29,333 | 909,293 / 29,333 |
| small / custom_scalar_key | 21467.89 / 21718.12 | 9782.22 / 10468.52 | 2.07× | 30,976 / 1,000 | 30,976 / 1,000 |
| small / custom_time_range | 55135.12 / 164008.77 | 3133.30 / 3696.83 | 44.36× | 9,600,000 / 352 | 9,600,000 / 352 |
| small / custom_numeric_threshold | 146628.88 / 179059.74 | 12675.69 / 13685.92 | 13.08× | 8,814,293 / 284,333 | 8,814,293 / 284,333 |

Small 旧路径 time-window 的五个原始样本（秒）为 54.152 / 54.194 / 55.135 / 151.100 / 164.009；P50/P95 均展示，不将最慢样本解释成稳定尾延迟。三类查询的 P50 提速最小为 2.19 倍。

下列 RSS 仅涵盖各 worker 的正式查询及结果校验，不含 parent、构建、其他引擎或额外插桩 pass。

| Dataset / worker | RSS before / after / peak MB |
| --- | ---: |
| smoke / legacy | 97.395 / 117.170 / 135.033 |
| smoke / pushdown | 97.300 / 116.515 / 134.717 |
| small / legacy | 97.231 / 117.809 / 136.315 |
| small / pushdown | 97.243 / 116.191 / 134.640 |

Small 仍可能超过 1 秒：该阶段验收为相对旧路径至少 2 倍改善，不替代 C2b 的完整交互预算。
EAV 存储大小不变，字段函数和时间筛选仍可能扫描大量 SQLite 行；fetched rows 减少不表示引擎已避免所有扫描。
数值/文本比较保留 Python，因此稀疏命中的阈值查询仍需解码单字段的大量候选。

## Validation

- `python -m pytest -q`：282 passed, 5 skipped。
- `python -m pytest -q benchmarks/test_benchmark.py`：19 passed。
- 新的生产语义/API targeted suite：78 passed。
- Desktop `npm test`：14 files / 69 passed；`npm run build`：tsc + Vite passed。
- compileall、release sanity、diff check，以及历史 31 个 baseline 文件逐字节 SHA256 校验通过。
- 未修改生产依赖、schema/version/index 定义、默认 backend、模板、compare、Diagnostics 或 Rerun。

## Follow-up

完成本阶段验收后，C2b 再设计 Typed SQLite stream/schema 存储、版本/重建与 Legacy 兼容路由，解决 EAV 空间放大。
随后单独改造 Diagnostics；Phase D 再处理 Rerun 排序、序列化与 SDK 调用成本。
time_sync 的 20 ms offset 已知正确性缺口仍单独跟踪。

历史布局/引擎比较见 [Phase C](query-storage-phase-c.md)与 [ADR-001](adr/ADR-001-query-storage.md)。
