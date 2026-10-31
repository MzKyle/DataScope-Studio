# Phase E：CSV 构建与精确查询闭环

本阶段面向完整 32 字段、300 万行 CSV，沿用 SQLite。两份同规模、不同 seed 的
Recording 验证对比查询。历史基线文件保持原样；对照生产代码固定为提交
`ab8473317b904388448bb3b5c83cc01bede35e30`，通过 `git archive` 在独立进程导入。

## 存储与写入

数据库 v5 只新增 `typed_summaries`，不重写 v4 的样本表、EAV 行或 Recording。
样本格式仍为 v1。摘要、字典、样本、索引及 registry 在同一事务发布；取消或失败时回滚。
最后一个 schema 使用者被删除后，其物理表及索引一并释放。v4 程序不能直接打开 v5 工作区。

CSV 读取及推断边界仍为 pandas 50,000 行。列转换与 executemany 的批次按映射宽度缩小，
Python 转换工作缓冲预算为 64 MiB；它不是整个进程或 pandas/Rerun 原生分配的 RSS 上限。
原生相对数值时间轴按列转换，epoch、字符串、复杂或不安全时间继续调用原标量转换。
保留 int64、bool、负零 BLOB、重复映射、块内排序及缺失值语义。

仅为 battery 元数据匹配到的 numeric 物理列增加 `(dataset_id, value, time, sample_seq)`
覆盖索引。同一物理列去重；其他列继续使用时间索引。Custom Query 仍先按原规则转 float，
模板保持原生数值比较。索引候选边界向外扩一个 ULP，并保留 TEXT/BLOB 编码进入原有校验，
最终结果由原过滤规则确认。

## 精确聚合

构建摘要时每个 dataset 只进行一次按时间、采样序号排序的宽扫描。数值写入任务专属的
float64 暂存文件，再把完整有序值流交给 Python `sum()`；不合并分块 sum，不使用 SQL AVG。
重复 mapping 的 multiplicity 在求和序列中展开，而不是在最终 sum 上乘倍数。
min/max 的相等值保持首次出现的符号；latest 保留原始类型。

缓存按 `(recording_id, entity_path, key)` 保存，带算法与 Python 实现/主次版本标识。
存在 EAV 重叠、不同物理列合并、运行时不匹配或旧数据无摘要时，通过有序原生值流精确计算。
高基数文本状态不缓存无限增长的字典。查询不写缓存、不改变 Catalog。

`compare(series)` 按输出 limit 流式读取；`state_duration` 保留原分组首次出现顺序，
读取一个额外样本计算边界 duration，最后一个样本仍为零。非标准 Core limit 参数沿用原路径。

## 入口与恢复

Core/API/CLI 接受 `auto | legacy | typed_sqlite`。`auto` 仅为 CSV 选择 typed，
非 CSV 走 legacy，不支持的 CSV stream 仍走 EAV 残余。单源任务入队前解析实际策略；
批量任务保存所选策略，并在处理每个 source 时解析。旧 Job 缺少字段时固定 legacy。

桌面项目构建、Quick Inspect 与批量构建传递同一个策略，高级选项显示“自动/兼容模式”。
构建结果及 Recording 参数记录实际存储、回退 stream 和写入/索引/摘要子阶段。
默认值由 core 与 desktop 的显式常量控制，只有全部验收完成后才改为 auto。

取消意图先通过任务或 batch item 标记文件送达，再等待 SQLite 写锁；长 SQL 的 progress
handler 可以中断。中断恢复按精确 Job 所属清理未完成 Recording，保留已成功的 batch item。
typed 任务的数据库取消状态最多每 250 ms 读取一次，既有取消点仍立即检查标记文件，
索引提交后强制再检查一次；避免将频繁 SQLite 连接开销带进 Rerun 和精确求和循环。
摘要暂存位于任务 cache 中，正常或异常退出显式关闭；硬中断由已有任务恢复流程清理。

磁盘预估分别按 Catalog/WAL、项目 cache 中的精确摘要与排序暂存、输出目录 RRD/RBL 的实际
位置预算；支持自定义项目目录与 Catalog、输出各处于不同设备。同设备合并预算，不同设备分别
检查并分别保留余量；批量估算传递同一个策略并计入源文件复制。项目包仍不携带查询索引或摘要。

## 验收协议

```powershell
.venv/Scripts/python.exe -m benchmarks.csv_performance --preset smoke
.venv/Scripts/python.exe -m benchmarks.csv_performance --preset small
.venv/Scripts/python.exe -m benchmarks.csv_performance --preset medium
```

标准协议固定三次构建、一次查询预热和五次正式查询。control 对主 Recording 构建三次；
新索引和完整 Workspace 每轮都构建两份同规模输入。加速比只比较配对的主 Recording。
完整 Recording 的计时范围为 `build_recording()`；导入（reference 模式）、inspect 与
Mapping 保存分别列在 `phases`，不混入这一时长。
`--rows` 或改变轮数属于开发运行，报告不会标为标准协议。
`--input-manifest` 可复用完整输入和独立 oracle，配置、行数与 CSV 校验和必须一致，
所有旧/新计时 worker 仍重新运行，不复用旧计时样本。

独立 oracle 直接读取原 CSV，独立计算全部 32 字段的精确聚合；仅共享既定 pandas CSV
解析契约，不使用生产 reader、SQL、摘要或聚合函数。诊断完整报告另与冻结 C3 实现对照。
SQL/EXPLAIN 与解码计数在独立非计时 pass 收集。游标返回数不是 SQLite 实际扫描量。
父进程每 100 ms 记录任务的 float64 暂存、SQLite WAL/journal 与 CSV 排序缓存字节峰值；
该值不包含源 CSV、主 Catalog、RRD/RBL 或不可观察的 SQLite 原生临时 I/O。
正式查询为热缓存单机顺序测量，五次样本的 P95 是最大值，不代表生产 tail SLO。

| 项目 | Medium 门槛 |
| --- | --- |
| 七类查询及两份同规模全字段 compare | 每项 P95 ≤1 秒 |
| 单份完整诊断 | P95 ≤60 秒；Smoke/Small 继续 ≤5 秒 |
| 主 Recording 查询索引，含摘要、提交及 checkpoint | 中位数 ≤180 秒、较同轮旧实现 ≥3 倍 |
| 单份完整 Recording 构建 | 中位数 ≤300 秒 |
| 完整 Catalog / 两份源 CSV 总大小 | ≤2 倍 |
| 新构建进程树 RSS | ≤1 GiB |
| 查询与诊断阶段 RSS | ≤512 MiB |

Medium 的空 CSV `time_sync` 不计作传感器同步验收。Large 仅作资源压力测试，达到资源限制时
保留 incomplete 及已有测量。当前 Windows 验证不能替代 Linux/macOS 安装和运行回归；
Quality workflow 已增加三个平台的存储兼容性矩阵。

对于 typed 长事务，心跳线程在 SQLITE_BUSY/SQLITE_LOCKED 后重试。恢复时若数据库心跳暂时
过期，额外检查 worker 的实际 Job 命令归属，避免把仍在构建的进程当作孤立任务；macOS 的
命令检查使用 `ps`，不依赖 Linux `/proc`。

本机正式验收已完成，结果、原始样本、失败记录和哈希见
[2026-10-20 验收归档](../../benchmarks/results/baselines/2026-10-20-phase-e/README.md)。
Medium 索引中位数 56.313 秒、同轮加速 3.216 倍，完整 Recording 中位数 149.570 秒；
最慢查询 P95 691.802 ms，全字段 compare P95 3.677 ms，诊断 P95 16.039 秒。
Large 1200 万行、3.805 GB 输入完整构建 612.789 秒并通过 RRD verify。
跨平台原生安装包及外部 CI 尚未验证，因此继续保持 legacy 默认值；显式 auto 可使用新路径。
