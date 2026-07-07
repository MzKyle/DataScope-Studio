# 桌面前端

前端入口：

```text
apps/desktop/src/main.tsx
apps/desktop/src/App.tsx
apps/desktop/src/app/AppProviders.tsx
apps/desktop/src/api.ts
apps/desktop/src/i18n.ts
apps/desktop/src/styles.css
```

## 状态组织

`App.tsx` 只保留应用入口和兼容导出。桌面主工作台在
`features/studio/StudioWorkspace.tsx`，现有业务组件仍按 Dashboard、Import、
Recordings、Diagnostics、Extensions、Settings 分区组织。

状态边界：

- TanStack Query 负责服务端状态缓存和刷新，query key 统一定义在 `app/query-keys.ts`。
- Zustand 负责前端 UI 状态、导入草稿、Mapping 草稿和用户偏好，位于 `stores/`。
- 组件内 state 只保留真正局部的展开、筛选和临时输入状态。

## API Client

`api.ts` 封装 HTTP 请求，并处理统一错误格式。新增后端接口时应先扩展 `types.ts`，再扩展 `api.ts`。

## 样式系统

`styles.css` 使用 design tokens 定义颜色、间距、圆角、阴影、按钮、输入框和卡片。默认主题为浅色。
前端已接入 Tailwind v4 和 shadcn/ui 风格的本地 primitives：

- 通用组件位于 `ui/`，优先使用 Radix primitives 提供可访问交互。
- 新增页面 UI 优先组合本地 `Button`、`Badge`、`Card`、`Tabs`、`Dialog`、`DataTable`。
- 不引入完整 UI 组件库；保持工程工作台风格、高密度布局和 8px 圆角。

## 文件选择

桌面端使用 Tauri dialog 插件选择文件或文件夹。浏览器环境下会退化为手动路径输入。
