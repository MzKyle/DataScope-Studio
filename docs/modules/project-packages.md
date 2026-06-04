# 项目包

项目包用于把一个本地 project 的 catalog 元数据和 artifact 打包成 zip，便于备份、迁移或共享。

## 导出

CLI：

```bash
datascope project export --project demo --out ~/DataScopeExports
```

如果 `--out` 是目录，DataScope 会自动生成 zip 文件名。如果不传 `--out`，默认导出到：

```text
~/DataScope Studio Exports
```

## 导入

CLI：

```bash
datascope project import ~/DataScopeExports/demo_project.zip
```

桌面端可以在 Quick Actions 中打开项目包。导入时会把 artifacts 复制到当前 workspace，并重写 catalog 里的本地路径。

## 包内容

项目包包含：

- `manifest.json`
- sources 元数据
- mappings
- recordings
- blueprints
- query exports
- templates metadata
