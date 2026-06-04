# 桌面前端

前端入口：

```text
apps/desktop/src/main.tsx
apps/desktop/src/App.tsx
apps/desktop/src/api.ts
apps/desktop/src/i18n.ts
apps/desktop/src/styles.css
```

## 状态组织

`App.tsx` 管理当前项目、source path、inspect 结果、mapping、recording、query、batch、plugin/template registry 和 UI section。

## API Client

`api.ts` 封装 HTTP 请求，并处理统一错误格式。新增后端接口时应先扩展 `types.ts`，再扩展 `api.ts`。

## 样式系统

`styles.css` 使用 design tokens 定义颜色、间距、圆角、阴影、按钮、输入框和卡片。默认主题为浅色。

## 文件选择

桌面端使用 Tauri dialog 插件选择文件或文件夹。浏览器环境下会退化为手动路径输入。
