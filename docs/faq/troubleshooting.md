# 故障排查 FAQ

## 后端健康检查失败

确认 API 正在运行：

```bash
curl --noproxy 127.0.0.1 http://127.0.0.1:8000/api/health
```

如果本机设置了代理，`127.0.0.1` 请求可能被代理劫持。使用 `--noproxy 127.0.0.1` 或临时取消代理环境变量。

## Node 版本不足

Vite 需要 Node 20.19+。桌面启动脚本会自动查找常见 Node 20 安装路径；否则请手动安装并加入 `PATH`。

## Tauri 显示 Connection terminated unexpectedly

先清理旧进程：

```bash
pkill -f 'target/debug/datascope-studio' || true
pkill -f 'vite --host 127.0.0.1' || true
```

仍然崩溃时使用：

```bash
cd apps/desktop
npm run tauri:dev:safe
```

## Rerun 无法打开

确认本机安装了 Rerun CLI：

```bash
rerun --version
```

没有安装时，DataScope 仍能生成 `.rrd/.rbl`，只是无法自动启动 viewer。

## Python int too large to convert to C long

通常是把 Unix 毫秒/微秒/纳秒当作 duration 秒写入。当前版本会自动归一化 `timestamp/time/t/datetime` 字段；如果仍出现，请检查 mapping 是否把时间列错误地映射成 scalar。
