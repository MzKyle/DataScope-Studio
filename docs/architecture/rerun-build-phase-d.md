# Phase D：CSV Rerun 构建

仅 CsvAdapter 提供可重放读取工厂。完整预检在创建 RRD 前完成，读取保持原 pandas 50,000 行类型推断边界。排序判定使用原主时间轴、归一化有效时间和源序号；跨批重复时间稳定，无效时间只在尾部才视为已排序。已排序输入直接重读，其他输入进入稳定 SQLite/pickle 外部排序。不可重放的输入保留原行写入。

预检也固定数值映射资格：scalar 仍选择第一个存在的列，scalar_group 保留子路径，缺失值跳过，值仍按原 `float()` 语义转换。字符串、跨块类型变化、非有限值等保留逐行路径；映射碰撞、实体规范不明确、混合或不安全时间以及缺少 SDK 能力时保守回退。不会在部分写入后改变执行路径。

只在已验证的 Rerun 0.33 SDK 能力齐备时使用 `Scalars.columns()` / `send_columns()`。显式 row/time 列使用 SDK 原标量转换的纳秒舍入，时间数组采用 `datetime64[ns]` / `timedelta64[ns]`，保留业务时间类型、值、负零和重复样本顺序。state、日志、几何等沿用原 writer。允许变化的是自动 log_tick/log_time、生成 ID 和物理 chunk 组织。

每个处理批次最多 50,000 行，按列和映射宽度收缩，Python 工作缓冲预算 64 MiB；外部排序参数缓冲同样受限。预检、每批和外部装载检查取消。源文件状态在预检前后和写入前后检查，异常交由现有 Workspace 清理流程处理。游标、连接、生成器和 SDK stream 显式关闭。

## 测量范围

独立入口：`python -m benchmarks.rerun_build --preset smoke|small|medium`。

冻结旧 writer 仅存在于 benchmarks。Windows 上原外部排序的连接释放会阻止删除暂存数据库，基准对旧 writer 使用只修正资源关闭的 shim，保留冻结源码、排序、pickle、逐行 SDK 调用和业务语义。原始记录保留这一说明。

正式计时包含完整 CsvAdapter 读取、预检、排序、写入、flush/disconnect 和 orphan cleanup。Workspace `build_recording()` 总耗时另报，包含默认 legacy 查询索引、Blueprint 和产物验证。Smoke 旧新各一次预热、三次正式写入，另测排序和批量消融；Small 各一次完整 Workspace 构建，只报告 elapsed。Medium 仅新 writer，进程树限制 30 分钟及 2 GiB RSS，触限标记 incomplete。

插桩独立运行，归因采用互斥区间，嵌套 inclusive 区间不相加。SDK 内部原生序列化保留在 SDK 调用区间。暂存磁盘采样仅覆盖任务所有的 CSV 排序 cache；RRD 大小和独立 SDK 校验的临时文件另记。所有 RRD 使用真实 SDK 解码全部业务组件并保留 row/time 类型及纳秒值，随后运行 RRD verify；完整 Workspace 试验同时验证 Blueprint 产物。

该优化不改变 DB v4、query_storage 默认值或查询算法，也不代表 typed 默认切换门槛已全部通过。
