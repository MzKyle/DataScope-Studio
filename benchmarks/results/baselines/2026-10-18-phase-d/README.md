# Phase D：CSV Rerun 独立测量

标准完整 32 字段 fixture 保持不变。Smoke / Small / Medium 分别为 30,000 / 300,000 / 3,000,000 源采样行。输入、冻结 writer、生产模块和基准工具的 SHA256 随原始报告保存；冻结 writer 逐字节对应提交 `98c252c` 的原模块。

`before_optimization_profile.json` 是编写优化代码前的独立插桩结果。其 95.31 秒包含插桩开销，不能当作正式旧路径中位数。互斥归因中 SDK 调用 44.82 秒、archetype/Arrow 构造 25.04 秒，pickle 与 SQLite 排序各阶段不足 1 秒；因此重点减少每个数值的 Python/SDK 调用，排序快速路径作为补充。SDK 原生序列化留在 SDK 调用区间，inclusive 嵌套时间不相加。旧 writer 在 Windows 的暂存数据库释放问题仅由资源关闭 shim 处理，源码、排序、pickle 和业务调用保持冻结。

正式协议：Smoke 每路径一次预热、三次完整写入；排序单独、批量单独各一次；旧新完整 Workspace 各一次；旧新归因另行运行。Small 旧新各一次完整 Workspace，Rerun 子阶段与整体构建分别报告，不计算 P95。Small 另行装载完整输入验证排序空间和新路径全文件有序资格。Medium 只运行新路径，限制 30 分钟及 2 GiB 进程树 RSS，触限标记 incomplete。

正式耗时包含读取、预检、排序、写入、flush/disconnect 和 orphan cleanup。真实 SDK 解码全部业务组件，比较实体、值、row/time 类型、纳秒值与重复顺序；忽略已批准的 SDK 自动时钟、生成 ID 和物理 chunk 组织。每个文件执行 RRD verify。Medium 单路径只报告完整性和压力结果，`sdk_parity` 为 null，不宣称存在未运行的旧路径对照。

RSS、父进程每 100 ms 采样的任务排序数据库及 journal 字节、独立归因轮次每 20 ms 的 cache 采样分别标明范围；RRD 输出大小和 SDK 校验临时文件另记。这些指标不代表未测量的 SQLite 原生临时 I/O 或全机器磁盘峰值。Workspace 包含默认 legacy 查询索引、Blueprint 和验证成本；Rerun 提速只比较写入子阶段。

历史基线（含 C3）逐字节保留；数据库保持 v4，默认 query_storage 仍为 legacy。结果不替代 typed 默认切换或其他查询性能门槛。
