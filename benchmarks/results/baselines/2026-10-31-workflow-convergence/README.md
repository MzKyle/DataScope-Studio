# Workflow convergence: Quick Inspect

Windows 上两万行 CSV、9 列（时间、6 个数值、状态与日志），每条路径三个独立 Python 进程，交替运行；复制同一源文件，使用默认 legacy 索引。原始计时、输入 SHA256、依赖版本和 RRD 语义指纹见 quick-inspect.json。

计时分别包围 add_source/inspect/save_mapping、adapter.convert、_index_recording 和完整 build_recording；总耗时包含导入及构建。轻量路径使用 _manage_job=False、_build_query_index=False。每轮创建新 Workspace；不复用已建立的索引。

生成输入使用 timestamp=i*0.01、battery=(i%100)/100、temperature=20+i%50、pressure=100+i%20、speed=i%10、voltage=12+i%3、current=i%5；state 交替 running/idle，message 每 1000 行为 ERROR、其余为 ok。

RRD 对照使用现有 benchmarks.rrd_contract.semantic_summary，验证全部业务组件、row 序列、纳秒时间类型和值及重复采样顺序，排除自动 SDK 时钟、ID 和 chunk 布局。六次构建指纹一致。

这是单机小工作负载测量，不能外推大文件、其他适配器、冷缓存或其他平台的加速比例。未测量此轮进程峰值内存；大型 CSV 资源预算沿用 Phase E 验收，不因本轮更改默认存储策略。
