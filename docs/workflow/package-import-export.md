# 项目导出与导入

## 导出项目

桌面端：

- 在 Settings 中设置默认导出目录。
- 在 Dashboard Quick Actions 中点击“导出项目”。

CLI：

```bash
datascope project export --project demo --out ~/DataScopeExports
```

## 打开过去导出的包

桌面端：

- 点击 Quick Actions 中的“打开项目包”。
- 选择 `.zip` 包。
- 导入完成后可直接在 Recent Runs 或 Recordings 中打开已有 `.rrd`。

CLI：

```bash
datascope project import ~/DataScopeExports/demo.zip
```

导入会重写包内 artifact 的本地路径，避免依赖原机器目录。
