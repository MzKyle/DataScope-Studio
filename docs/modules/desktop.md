# 桌面端

桌面端位于 `apps/desktop`，技术栈是 Tauri 2、React、TypeScript、Vite 和 lucide-react。

## UI 模块

| 区域 | 说明 |
| --- | --- |
| Dashboard | 当前项目、导入入口、快速操作、最近 runs |
| Import | source inspect、mapping、preview、build recording |
| Recordings | recording 列表、标签、打开 Rerun |
| Query | 查询模板、结果表、导出 |
| Templates / Plugins | 本地模板和插件 registry |
| Settings | 语言切换、默认导出目录 |

## 性能原则

- 主内容区独立滚动，减少 WebKitGTK 重绘。
- 大列表默认截断显示，详细页再加载更多。
- 转换和查询由后端处理，前端只显示状态。
- 默认使用性能图形模式，`tauri:dev:safe` 只作为 WebKit 崩溃兜底。
