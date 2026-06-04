# FastAPI 服务

API 入口：

```python
from datascope_api.main import app
```

开发启动：

```bash
uvicorn datascope_api.main:app --reload --host 127.0.0.1 --port 8000
```

## 错误格式

API 失败统一返回：

```json
{
  "error": {
    "code": "validation_error",
    "message": "..."
  }
}
```

路由内部通过 `_guard()` 包装 `Workspace` 调用，把常见异常转换为可读错误。

## CORS

默认允许本地 Vite / Tauri 访问：

- `http://localhost:1420`
- `http://127.0.0.1:1420`
- `tauri://localhost`
- `http://tauri.localhost`
- `https://tauri.localhost`
