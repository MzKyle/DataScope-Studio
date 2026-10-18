# Phase C2b：Typed SQLite 存储与兼容读取

本阶段为 CSV 的 scalar、scalar_group、state 增加显式启用的 typed 查询索引。默认仍为 legacy；旧 Recording 不重建。
查询模板、Custom Query 的数值/文本筛选、compare 和 Diagnostics 继续使用现有业务函数。
完整查询 SQL 执行和 Diagnostics 性能改造属于后续阶段。

## 启用与兼容

```bash
datascope import robot.csv --project Robot --query-storage typed_sqlite
```

Core 的 `build_recording()`、`enqueue_build_recording()` 新增 keyword-only `query_storage`，取值为 `legacy`、`typed_sqlite`，默认 `legacy`。
`POST /api/recordings/build` 接受同名可选字段；无效值返回 422。Job 保存该选项，重试沿用；batch 和 Quick Inspect 保持原默认，Desktop 暂无新开关。
现有构建和查询返回结构保持兼容。读取按 registry 中的实际布局路由，后续采用 legacy 构建不会隐藏已经存在的 typed 数据。
非 CSV 输入继续使用原 EAV writer。项目包仍携带原始输入、artifact 和元数据，不新增查询索引导入导出协议。

打开 Workspace 时将 metadata.sqlite 升级至 v4，迁移仅增加 typed registry，不重写 query_rows、旧索引或 Recording。
仅支持 v3 的旧程序会拒绝打开 v4；停止 typed 新写入不会降级数据库，也不能据此声称可以直接回滚旧二进制。

## 布局和类型

- `typed_indexes` 记录格式版本、源 checksum、mapping/timeline 和构建统计；`typed_schemas` 描述物理列编码。
- `typed_datasets` 用整数 ID 将 Recording 绑定到 schema；相同 schema 复用样本表。
- `typed_bindings` 保留逻辑 stream 的字段、路径、semantic、列位置及 mapping 顺序；重复映射仍产生重复逻辑值。
- `typed_states` 用有界 Python cache 和 SQLite 字典保存 state 值；字典保留原 JSON 类型，样本只存整数代码。
- `typed_legacy_order` 仅为新混合索引的 EAV 残余行记录采样、mapping 顺序，不复制其值。

同一 CSV、同一采样行和时间轴上的数值字段合并为 numeric 宽行，state 合并为独立采样组。
不会按自动推断产生的每个单字段 stream 单独保存一行。每个采样组最多 128 列，超出时分组；没有跨独立时间轴的 join 或补齐。
全空的物理采样行不保存，单个空值不产生逻辑查询行；null 时间仍可保存。

沿用旧 writer 的 pandas CSV 解析、50,000 行分块、时间单位和每块排序方式。
完整预检确定字段类型之后才开始索引事务；预检不是前 1,000 行 profile 推断。
int64 保留整数精度，bool 与整数有不同解码类型，float 不经整数/字符串强制转换。
SQLite REAL 会丢失负零符号，因此只对 `-0.0` 使用固定的 8 字节 IEEE754 BLOB 转义，reader 恢复浮点负零。
未来的数值 SQL 编译器必须处理该编码，不能假定 REAL affinity 列的所有非空单元都具有 SQLite REAL storage class。
跨分块类型变化、超出 int64、非有限数值及其他不支持类型使整个逻辑 stream 使用 EAV；支持的 stream 不双写。
预检/写入之间及结束时校验文件大小和修改时间，输入变动导致构建失败并回滚。

每个样本表只有 `(dataset_id, time, sample_seq)` 时间索引，标准 32 字段输入有两个样本索引。
新表装载后创建索引并运行 ANALYZE；复用已有 schema 时维护现有索引并更新统计信息。
没有为所有字段、battery 或 state value 增加索引，因为本阶段仍由 Python 执行值筛选和聚合。

## 查询与生命周期

C2a 私有计划明确提供元数据条件和有限时间边界，不解析 SQL 字符串。
key/path 在少量 binding 上筛选，保留 Python Unicode lower、trim、instr 子串和字面 `%`/`_` 语义；有限闭区间边界进入样本 SQL。
模板和 compare 原有 SQL 元数据匹配规则保持原样，不能借存储迁移改变这些规则。

reader 只为选中的字段创建有序投影游标，按四个既有排序字段归并 typed 和 EAV 逻辑行。
对于四字段完全相同的记录，原 SQLite 路径未定义平局顺序，实测会随查询计划变化；本阶段明确使用原写入顺序，legacy 以 rowid、typed 以采样/mapping 序号稳定该顺序。
业务函数继续消费原逻辑行结构；残余过滤存在时不提前 LIMIT。流式查询在取得输出 limit 后关闭全部游标和连接。
compare 和 Diagnostics 的完整输入、Python 聚合和物化成本仍然存在。

cleanup、DDL、typed samples、EAV 残余、字典和 registry 在同一 SQLite 事务提交。
每个写入批次检查取消；typed Job 先写任务专属取消标记，再更新数据库状态，避免取消意图被长写事务阻塞。
SQLite progress handler 也检查该标记，索引创建期间同样可中断；异常转换为既有 JobCancelled 并回滚。
硬中断恢复按 Recording 中记录的精确 Job 归属清理，不能因 artifact 同名而删除先前成功构建。
删除最后一个 schema 使用者时释放表和字典；SQLite 可以复用 freelist 页面，文件不会自动缩小，不在后台自动 VACUUM。
未知格式、缺失样本表或字典、数据库错误正常报错，不通过空结果或后端回退隐藏错误。

## 验证与测量

运行方式：

```bash
python -m pytest -q
python -m pytest -q benchmarks/test_benchmark.py
python -m benchmarks.typed_storage --preset smoke
python -m benchmarks.typed_storage --preset small
python -m benchmarks.typed_storage --preset medium
python -m compileall -q packages/core/src benchmarks
python packaging/release/sanity_check.py
```

Smoke/Small 对照保留 C2a 下推的真实生产 EAV 路径，使用相同旧 Catalog 和 CSV，并以只读方式打开旧 Catalog。
EAV、typed time、typed none 在独立进程顺序执行，每项一次预热、五次正式测量。
none 是 benchmark 内拦截样本 CREATE INDEX 的实验，不增加生产开关；旧 EAV 索引和所有元数据结构保持一致。
Medium 只测生产 typed 索引构建和空间，对照同输入的已归档 Phase C EAV 空间证据，不重放其昂贵载入，也不声称同轮 Medium 查询提速。
各档均不执行 Rerun conversion，构建时间明确指 Query Index，不代表完整 Recording 构建。

原始 JSON 保存完整耗时、SQL/EXPLAIN、RSS、源和代码哈希。读取/解码计数在独立的非计时 pass 完成。
投影游标返回数可能对同一物理采样行重复计数；独立候选统计描述 WHERE 时间条件后的 dataset 样本，不将其解释为 SQLite 页读取或内部扫描数。
物理行与逻辑值数量另以 SQL COUNT 校验 writer 统计。
若当前 SQLite 未启用 dbstat，报告对象大小为 null，改用完整 checkpoint Catalog 字节及索引阶段分配页面报告空间，不伪造逐对象大小。

验收要求保留全部 32 字段、无 EAV 回退、物理采样行不超过源行两倍、查询 Catalog 不超过 CSV 两倍且比 EAV 减少至少 80%。
索引实验记录增加的空间、创建时间和实际查询收益，不增加当前读取入口未使用的索引。
结果归档见 [C2b baselines](../../benchmarks/results/baselines/2026-10-18-phase-c2b/README.md)。

本机 Small 的 9,632,000 个逻辑值保存为 602,000 条物理样本，Catalog 为 115.220 MB，较只读 EAV 控制的 2,478.957 MB 减少 95.35%。
两个时间索引使晚时间窗口 P95 从无样本索引的 5,590.94 ms 降至 13.02 ms；增加的 Catalog 空间约 13.47 MB。
compare P95 仍为 11,570.04 ms，数值阈值 P95 为 5,676.98 ms，不能以存储验收替代查询延迟验收。

Medium 完整保留 96,032,000 个逻辑值，物理采样行 6,002,000；Catalog 为 1,155.514 MB，约 CSV 的 1.216 倍，较历史同输入 EAV 空间减少 95.11%。
本轮生产 Query Index prepare 为 559.643 秒、worker 峰值 RSS 为 169.910 MB。
主 Recording 的预检、写入、建索引/ANALYZE 分别为 11.706 / 528.921 / 8.006 秒；总 prepare 还包含事务提交、连接及 checkpoint 等成本。
这不是固定 schema PoC 的 43.665 秒 prepare，也不是 Rerun 构建时间；两者写入/时间处理路径不同，不将历史 EAV prepare 用作同轮构建提速结论。
生产 writer 仍逐行调用原时间转换，并在 Python 处理各字段；后续需 profile 完整写入路径，再决定批量化改造。

回归结果：Python 全量 446 passed / 5 skipped，benchmark 21 passed，Desktop 14 个文件 / 69 tests passed，前端 tsc/Vite build、compileall、release sanity 和 diff 检查通过。

## 默认切换仍需满足的条件

本次交付只启用显式选择的 CSV 索引。JSONL/text、真实异步 stream 的 typed 写入、旧索引重建、完整 typed SQL 执行及 Diagnostics 优化尚未交付。
普通分析查询 P95 ≤ 1 秒与完整 Diagnostics P95 ≤ 5 秒仍是后续默认切换门槛，不能以本阶段空间收益替代。
后续还需在目标平台完成 typed 工作流安装/打包、真实数据、低内存和并发验收。

后续顺序：先为 typed 字段增加可证明等价的 SQL 执行和完整聚合，逐项对照七类旧查询；再改造 Diagnostics 的全量逻辑行物化，保留现有检查、阈值和结果。
索引候选随实际新 SQL 重新测量，不直接照搬 PoC 的四索引。写入的批量时间转换单独测量和验证时间边界；Rerun 优化仍作为 Phase D 独立验收。
