# C3 Diagnostics：原始对照与最终代码复验

标准 fixture 完整保留 32 字段。Smoke / Small / Medium 分别为 30,000 / 300,000 / 3,000,000 源采样行，输入和只读 Catalog 哈希见 JSON。

`initial_*.json` 和 Markdown 是第一轮对照的原始字节，包含冻结 C2c、新统计路径、SQL/EXPLAIN、RSS、独立计数及分组 oracle。`measured-source/` 保留该轮实测的三个生产模块。第一轮结束后补充了快照内项目校验、连接关闭和有字节上限的字符串字典缓存，最终代码由 `final_*.json` 单独复验，每档独立进程、一次预热、五次正式运行；`final_validation.py.txt` 保存复验入口。

最终复验使用第一轮的同一份完整 typed 数据。Small、Medium Catalog 是本任务自建副本的只读硬链接；Smoke 以相同原始 CSV 重建。完整报告及被最终 limit 裁剪的分组 findings 指纹同时与冻结对照 / 精确分组 oracle 校验。读取数明确区分逻辑值与样本游标返回行，不宣称测得 SQLite 扫描或页面 I/O。

第一轮 Small EAV 旧实现超过机器当时的 RSS 预算，原样保留失败和资源峰值，未缩小数据代替对照。Small 新 EAV 五次正式样本结束后，暂停过该轮的非计时插桩阶段以独立测量 Rerun；见 `interstage_pause.json`，正式耗时未暂停。第一轮 Medium 的预热和首个样本曾与 Rerun 草稿测试重叠，因此该轮耗时作为初测保留，以独立运行的最终复验替代性能结论。

EAV 新路径主要减少内存，Smoke 耗时没有改善；不据此声称所有布局均加速。非有限异常组继续采用原规则兼容计算，不承诺其有界内存或 5 秒延迟。Medium 为完整输入压力和精确结果校验，不属于本阶段 5 秒硬门槛。

旧的 54 个历史基线文件保持逐字节一致。数据库仍为 v4，构建默认 legacy，没有新增持久化索引。

## 最终复验

| typed 标准输入 | P50 | P95 | 验收 |
| --- | ---: | ---: | --- |
| Smoke | 0.153 s | 0.154 s | ≤ 5 s，通过 |
| Small | 4.016 s | 4.182 s | ≤ 5 s，通过 |
| Medium | 44.674 s | 49.909 s | 精确 oracle 通过；压力测量，无 5 s 承诺 |

三档完整报告、分组 findings 指纹、全部字段及只读 Catalog 检查均通过。Small 暂存累计写入 136.8 MB，不代表峰值占用；进程 RSS 与 Python 工作缓冲分别报告。

回归：完整 pytest 540 passed / 5 skipped；契约与 benchmark 联合测试 54 passed；Desktop 14 个文件、69 项测试和 build 通过；compileall、release sanity、diff 检查通过。命令与统计见 `verification.json`。
