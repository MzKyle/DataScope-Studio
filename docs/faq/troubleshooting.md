# 故障排查 FAQ

## 诊断日志在哪里

安装版会自动记录桌面启动、内置 API 启动、前端未捕获异常、文件读取错误和后台任务
崩溃。设置页的“诊断日志”卡片会显示当前机器上的准确路径。

默认日志目录：

| 系统 | 目录 |
| --- | --- |
| Linux | `~/.local/share/studio.datascope.desktop/logs/` |
| Windows | `%LOCALAPPDATA%\studio.datascope.desktop\logs\` |
| macOS | `~/Library/Logs/studio.datascope.desktop/` |

主要文件：

- `datascope-studio.log`：桌面启动、Tauri、前端 JavaScript 和 API 调用错误，格式为每行一个 JSON 对象。
- `datascope-api.log`：FastAPI/Uvicorn 输出、文件打不开等 API 错误。
- `<项目目录>/logs/job_*.log`：转换、批量导入等后台任务的输出与 Python traceback。

两个主日志文件达到约 2 MB 后会自动轮转为 `.1`、`.2`、`.3`。日志只保存在本机，
不会自动上传。提交问题时请附上故障发生时间附近的日志片段，并检查其中是否包含不希望
共享的本地路径。

如果安装后完全无法打开界面，可以从终端启动一次应用，再查看
`datascope-studio.log`。只要桌面进程成功开始执行，启动阶段错误和 Rust panic 都会写入
该文件；安装器自身在应用进程启动前发生的错误仍需查看操作系统安装日志。

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
