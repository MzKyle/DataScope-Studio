# 测试验收

## 自动测试

```bash
. .venv/bin/activate
pytest -q
```

## 前端构建

```bash
cd apps/desktop
npm run build
```

## Tauri 检查

```bash
cd apps/desktop/src-tauri
cargo check
```

## 仓库质量

```bash
git diff --check
git ls-files | rg '(^|/)\\.history(/|$)|(^|/)\\.venv(/|$)|(^|/)node_modules(/|$)|(^|/)target(/|$)|\\.rrd$|\\.rbl$|\\.zip$|\\.sqlite$|\\.env'
```

第二条命令应没有输出。
