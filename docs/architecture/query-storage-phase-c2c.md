# Phase C2c：生产 QueryBackend 与筛选查询下推

本阶段将已存在的 v4 typed Recording 接入保守的 SQL 筛选。构建默认仍为 `legacy`，
显式 `query_storage=typed_sqlite` 的行为不变；不迁移数据、不增加索引、不修改公开查询接口。
完整聚合、Diagnostics 性能和默认启用 typed 构建仍属于后续阶段。

## 内部边界与路由

`QueryBackend` 只定义 `plan()` 和 `iter_rows()`，不包含未使用的构建、删除或通用聚合接口。
内部请求携带项目、Recording、semantic、过滤条件、模板参数及结果 limit；执行计划保存 SQL、
参数、数据源、残余过滤标志及选择原因。生产模块不依赖 benchmarks。

Workspace 保留验证、结果组装、原 Python 业务函数及导出。路由器在同一个 SQLite 读取事务内
检查实际 registry 和 binding，而不是根据当前构建选项、源文件扩展名或猜测后端。

| 数据或操作 | 路径 |
| --- | --- |
| 旧 Recording / 新索引中的 EAV 残余 | LegacyQueryBackend，保留 C2a 下推 |
| 支持筛选的 typed binding | TypedSQLiteBackend，SQL 返回匹配候选 |
| 暂不支持的 typed 条件 | 原 typed 解码与 Python 过滤，值仍从 typed 表读取 |
| compare、state_duration、Diagnostics 原始行输入 | 兼容读取，保留全部所需输入及原算法 |

各数据源只分配一次，EAV 残余不会因为 Recording 有 typed registry 而被排除。
有序游标按 Recording、时间、路径、key 归并，同键继续按采样/映射顺序（旧 EAV 使用 rowid）排序。
只有分支的全部过滤已执行、limit 为正整数时，才允许该分支取前 N 条；残余过滤不截断候选。
全局 Python 业务函数继续控制最终输出数量，Core 非标准 limit 行为保持兼容。
提前停止、计划失败和读取异常均关闭游标与连接。

C2c 没有存储格式变更，读取代码可回退至支持 v4 的 C2b 实现；这不构成数据库降级，
v4 工作区仍不能直接交给仅支持 v3 的旧程序。

能力不足会选择兼容执行；SQL 错误、未知格式、非法编码及丢失的 state 字典引用正常报错，
不会用空结果或自动切换后端掩盖读取错误。

## 支持的 SQL 筛选

- 字段/路径在 binding 上筛选，有限闭区间时间进入样本 SQL。Custom Query 继续使用 Python
  Unicode lower 与 instr 子串语义，保留 trim 以及字面 `%`、`_`；模板的既有元数据规则不变。
- Custom Query 下推有限目标的 `gt/gte/lt/lte`。int/float 先按 Python `_filter_float()`
  语义转为浮点数再比较，bool 排除。数值字符串、文本、`eq`、`contains`、未知 operator
  及不能安全编译的参数继续由原函数处理，保留空输入下的延迟校验。
- `low_battery` 使用原生数字比较，保留 int/float/bool 规则，与 Custom Query 分开编译。
  仅正式模板调用传入参数时启用；Diagnostics 的元数据预筛选不使用默认阈值过滤原始行。
- 浮点列中的负零 BLOB 在独立 CASE 分支严格解码，普通数值使用 SQLite 表达式。
  非法 BLOB 报错；不依赖 JSON1。用户值全部绑定为参数，表名/列号由已有格式验证生成。
- `find_errors` 每个 dataset 最多检查 4096 个字典项，用原 Python 字符串转换和
  error/warn/fault 匹配计算代码集合，最多下推 500 个匹配代码；超限使用兼容读取。
  字典按 dataset 隔离，同次查询复用解析；text_log 保留 EAV 路径。

原查询函数仍验证 SQL 返回候选并组装结果。混合查询可同时包含 SQL 分支与 Python 残余分支，
因此只在单个字段上过滤成功不代表整个查询已无残余过滤。

## 验证与测量

新增 `benchmarks.query_backends`，其兼容控制固定自 C2b 提交 `73d4f8a` 的读取实现，
不经过被测生产后端编译器。C2b 存储 runner 也显式使用该控制，避免将新执行算法误标成旧基线。

```powershell
python -m benchmarks.query_backends --preset smoke
python -m benchmarks.query_backends --preset small
python -m benchmarks.query_backends --preset medium
```

Smoke/Small 复用只读历史 C2a EAV Catalog 及原 CSV；同轮生产 writer 创建一个 typed Catalog，
兼容与新路径在独立进程顺序只读查询同一文件。Medium 使用原 Phase C CSV，测量五类筛选查询，
不重新构建巨大的 EAV Catalog，也不声称同轮 Medium EAV 提速。

正式配置为一次预热、五次测量。SQL trace、EXPLAIN、候选计数和解码计数另行运行，
不进入正式耗时；报告保留原始样本、P50/P95、RSS、源码/输入 SHA256 与 Catalog 不变性校验。
游标返回的字段投影行、独立时间候选采样行、SQL 匹配候选和业务 JSON 解码分别计数；
当前 SQLite 接口不提供实际检查的行数或页数，报告明确以 null 表示，不用返回行冒充扫描量。
P95 使用五次正式样本的 nearest-rank（即最大值），表示本机本轮顺序测量结果，不代表稳定生产 tail SLO。

Smoke/Small 的硬门槛为五类筛选查询各自 P95 ≤ 1 秒，且保留标准全部字段和所有逻辑值，
没有 EAV 回退。Medium 只报告延迟。state_duration、compare 在 Smoke/Small 做结果及性能回归，
不纳入本阶段延迟门槛；七类查询与 Diagnostics 的既定默认切换条件不变。

契约测试覆盖纯 EAV、纯 typed、混合布局、项目隔离、空 ID 列表、重复映射、Unicode、
null/重复时间、缺失值、int64/2^53 边界、bool、正负零、残余过滤、字典上限、损坏输入、
提前停止和并发读取。保留全部模板、compare、Diagnostics、导出、API、CLI 的结果回归。

## 本轮结果

Smoke 与 Small 五类筛选均通过 P95 ≤ 1 秒，三条路径的七类结果摘要完全一致。
以下为新 typed SQL 路径 P95，单位毫秒：

| 查询 | Smoke | Small | Medium（仅报告） |
| --- | ---: | ---: | ---: |
| find_errors | 9.39 | 34.45 | 284.46 |
| low_battery | 13.70 | 65.08 | 2075.09 |
| Custom 字段 | 9.84 | 7.08 | 46.72 |
| Custom 时间窗口 | 4.80 | 4.58 | 24.45 |
| Custom 数值阈值 | 19.85 | 75.30 | 2432.17 |

Small 同轮 C2b 兼容路径的 find_errors、low_battery、数值阈值 P95 分别为 2446.22、
4140.48、6288.59 ms。字段与时间查询在 C2b 已有元数据/时间下推，本阶段保持低延迟。
晚时间窗口保留全部 32 字段，向 Python 返回 352 个逻辑值，对应两个采样组共 22 行窗口候选。
数值阈值新路径只解码 1000 个匹配值；兼容路径需处理大量前置不匹配候选。

Small 新路径 compare P95 仍为 13192.19 ms，state_duration 为 3856.03 ms。
这两项没有聚合算法改造，波动不视为聚合优化收益；Diagnostics 性能没有在本阶段验收。

Medium 两条 typed 路径的五类结果完全一致。兼容路径 find_errors、low_battery、数值阈值
P95 分别为 26745.29、44753.74、65955.77 ms；新路径分别提速约 94.0、21.6、27.1 倍。
Medium 的字段/时间查询本轮比兼容路径稍慢，绝对延迟仍低于 50 ms，不宣称所有查询均提速。
完整生产索引构建为 549.74 秒，属于未改造的 C2b writer；新查询进程峰值 RSS 约 103.17 MB。
Medium 两类数值筛选仍超过 1 秒，不能宣布已通过完整默认切换门槛。

回归：完整 pytest 510 passed、5 skipped，benchmark tests 23 passed；Desktop 14 个文件、
69 项测试及 tsc/Vite build 通过，compileall、release sanity、git diff --check 通过。

原始报告及哈希校验归档见 [C2c baseline](../../benchmarks/results/baselines/2026-10-18-phase-c2c/README.md)。
