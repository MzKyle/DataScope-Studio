# C3：精确 Diagnostics 与按规则读取

公开 Workspace、API、CLI、Desktop 和导出格式保持原契约。数据库仍为 v4，构建默认仍为 `legacy`，没有新增持久化索引或重写旧 Recording。

`diagnostic_reader.py` 在一个 SQLite 读取事务中解析 registry、binding 和 schema，形成私有读取计划。topic summary 保留完整输入；告警复用现有模板筛选及分别限制的样本数。typed 时间和质量统计按 dataset 一次宽投影读取，保留重复 binding 的逻辑 multiplicity；EAV 残余以一次有序扫描同时处理相应规则。

数值经原生类型校验后以查询内的短生命周期二进制批次进入 NumPy，不构造逐字段 JSON 查询行。每批最多 50,000 行，并按投影宽度收缩。Python 样本工作缓冲为 64 MiB；紧凑 float64 分组超出驻留配额后进入任务独占的共享暂存文件。精确排序超过单组预算时使用有限扇入外部归并；不引入依赖或近似分位数。

时间组保持 `(recording_id, source_id, entity_path)`，跨 key 的时间重复仍计入；只使用严格正间隔。若最大间隔小于最小正间隔乘阈值，可以精确证明不会产生 gap finding；其他组仍计算精确中位数。IQR 保留奇数排除中央值的上下半组中位数算法，bool 排除、int 转 float、state 字符串和首个常量证据保持原语义。非有限异常只回退对应组，在同一快照重放原规则；该回退不承诺有界内存或 5 秒延迟。

诊断报告的 findings 顺序、ID、各层 limit、去重、checks、证据、健康评分和逻辑 `query_row_count` 保持兼容。汇总完整 findings 后只保存请求的前缀。快照、游标、暂存文件在正常结束及异常时显式释放。

## 可复现实验

```powershell
python -m benchmarks.diagnostics --preset smoke
python -m benchmarks.diagnostics --preset small
python -m benchmarks.diagnostics --preset medium
```

冻结的 C2c Workspace 和规则位于 benchmarks 内；生产不依赖该模块。Smoke/Small 各路径在独立进程顺序执行，预热一次、正式五次。历史 EAV Catalog 只读，typed 的新旧实现使用同一个只读 Catalog。完整报告以 SHA256 对照，原始耗时、环境、输入与源码哈希、RSS、SQL/EXPLAIN、独立计数轮次和暂存写入量保存在 JSON。

旧全量实现超过当前机器可用内存预算时，保留真实失败及峰值，不减小 fixture，并增加独立精确分组 oracle。Medium 使用相同 32 字段 CSV，每次只把一个组交给冻结的原规则，不以旧实现的全部逻辑行列表为运行前提。基准 RSS 包含 SQLite、Python、NumPy 等进程开销，不能与 64 MiB 工作缓冲混为一谈；游标返回的样本数也不是 SQLite 实际扫描行数。

本阶段只对标准 typed Smoke/Small 的完整 Diagnostics 验收 P95 ≤ 5 秒。EAV、混合布局和 Medium 报告实测收益及资源；compare、state_duration、time_sync 和 typed 默认构建切换不在本阶段验收范围内。

## 2026-10-18 验收

最终代码独立复验，完整 32 字段 typed Smoke P95 为 **0.154 秒**，Small 为 **4.182 秒**，均满足 5 秒门槛；RSS 峰值分别为 142.7 MB、154.2 MB。Small 完整处理 960 万逻辑值，样本游标返回 60 万宽行。两档完整报告和全部分组 findings 与冻结对照 / 精确 oracle 一致，未发生异常组回退。

初轮冻结 typed 对照 P95 分别为 18.011 秒、177.995 秒。EAV Smoke 新路径 P95 为 24.461 秒，旧路径为 20.235 秒，RSS 从 866.2 MB 降为 129.9 MB；EAV 的主要收益是内存，不能宣称耗时也改善。Small 旧 EAV 因 RSS 预算失败，保留真实失败，不生成替代对照。

最终 Medium 完整处理 9,600 万逻辑值，精确 oracle 通过，P95 为 49.909 秒；该档继续作为压力测量，不宣称满足 5 秒门槛。

原始对照、最终复验、源码及输入哈希和已知测量限制见[归档说明](../../benchmarks/results/baselines/2026-10-18-phase-c3/README.md)。初轮与最终代码的差异、Medium 初测并发干扰及最终独立复测在归档中明确区分。
