use std::env;
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager};

#[derive(serde::Deserialize)]
struct ApiRequest {
    method: String,
    path: String,
    body: Option<String>,
}

#[derive(serde::Serialize)]
struct ApiResponse {
    status: u16,
    body: String,
}

#[derive(serde::Serialize)]
struct ApiStatus {
    status: String,
    port: u16,
    packaged_runtime: bool,
    runtime_dir: Option<String>,
    rerun_available: bool,
}

struct BackendState {
    port: u16,
    packaged_runtime: bool,
    runtime_dir: Option<PathBuf>,
    rerun_available: bool,
    child: Mutex<Option<Child>>,
}

impl Drop for BackendState {
    fn drop(&mut self) {
        if let Ok(child_slot) = self.child.get_mut() {
            if let Some(mut child) = child_slot.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

#[tauri::command]
async fn api_request(
    request: ApiRequest,
    state: tauri::State<'_, BackendState>,
) -> Result<ApiResponse, String> {
    let port = state.port;
    tauri::async_runtime::spawn_blocking(move || perform_api_request(request, port))
        .await
        .map_err(|err| format!("API task failed: {err}"))?
}

#[tauri::command]
async fn api_status(state: tauri::State<'_, BackendState>) -> Result<ApiStatus, String> {
    Ok(ApiStatus {
        status: if api_ready(state.port) {
            "online".to_string()
        } else {
            "offline".to_string()
        },
        port: state.port,
        packaged_runtime: state.packaged_runtime,
        runtime_dir: state
            .runtime_dir
            .as_ref()
            .map(|path| path.to_string_lossy().to_string()),
        rerun_available: state.rerun_available,
    })
}

fn perform_api_request(request: ApiRequest, port: u16) -> Result<ApiResponse, String> {
    let method = request.method.to_uppercase();
    if !matches!(method.as_str(), "GET" | "POST" | "PATCH") {
        return Err(format!("unsupported API method: {method}"));
    }
    if !request.path.starts_with("/api/")
        || request.path.contains('\r')
        || request.path.contains('\n')
    {
        return Err("unsupported API path".to_string());
    }

    let body = request.body.unwrap_or_default();
    let address: SocketAddr = format!("127.0.0.1:{port}")
        .parse()
        .map_err(|err| format!("invalid API address: {err}"))?;
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_secs(3))
        .map_err(|err| format!("could not reach DataScope API: {err}"))?;
    stream
        .set_read_timeout(Some(Duration::from_secs(600)))
        .map_err(|err| format!("could not set API read timeout: {err}"))?;
    stream
        .set_write_timeout(Some(Duration::from_secs(10)))
        .map_err(|err| format!("could not set API write timeout: {err}"))?;

    let request_text = format!(
        "{method} {} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAccept: application/json\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        request.path,
        body.as_bytes().len(),
        body
    );
    stream
        .write_all(request_text.as_bytes())
        .map_err(|err| format!("could not write API request: {err}"))?;

    let mut response_bytes = Vec::new();
    stream
        .read_to_end(&mut response_bytes)
        .map_err(|err| format!("could not read API response: {err}"))?;
    let response_text = String::from_utf8_lossy(&response_bytes);
    let (headers, body) = response_text
        .split_once("\r\n\r\n")
        .ok_or_else(|| "invalid API response".to_string())?;
    let status = headers
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .and_then(|value| value.parse::<u16>().ok())
        .ok_or_else(|| "invalid API status".to_string())?;

    Ok(ApiResponse {
        status,
        body: body.to_string(),
    })
}

fn start_backend(app: &AppHandle) -> Result<BackendState, String> {
    if external_backend_enabled() {
        let port = env::var("DATASCOPE_API_PORT")
            .ok()
            .and_then(|value| value.parse::<u16>().ok())
            .unwrap_or(8000);
        return Ok(BackendState {
            port,
            packaged_runtime: false,
            runtime_dir: None,
            rerun_available: false,
            child: Mutex::new(None),
        });
    }

    let runtime_candidate = find_runtime_dir(app);
    let explicit_runtime = env::var_os("DATASCOPE_RUNTIME_DIR").is_some();
    let dev_python = if cfg!(debug_assertions) && !explicit_runtime {
        find_dev_python()
    } else {
        None
    };
    let (python, runtime_dir, packaged_runtime) = if let Some(python) = dev_python {
        // cargo run should execute editable workspace packages, not a stale bundled runtime.
        (python, None, false)
    } else if let Some(runtime_dir) = runtime_candidate {
        let python = find_runtime_python(&runtime_dir).ok_or_else(|| {
            format!(
                "DataScope Python runtime is incomplete: {}",
                runtime_dir.display()
            )
        })?;
        (python, Some(runtime_dir), true)
    } else if let Some(python) = find_dev_python() {
        (python, None, false)
    } else {
        return Err(
            "DataScope Python runtime was not found. Rebuild the packaged runtime or install the development .venv."
                .to_string(),
        );
    };

    let port = reserve_local_port()?;
    let log_path = backend_log_path(app)?;
    let log_file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .map_err(|err| format!("could not open API log file {}: {err}", log_path.display()))?;
    let err_file = log_file
        .try_clone()
        .map_err(|err| format!("could not clone API log file handle: {err}"))?;

    let mut command = Command::new(&python);
    let port_text = port.to_string();
    command
        .args([
            "-m",
            "datascope_api.launcher",
            "--host",
            "127.0.0.1",
            "--port",
            &port_text,
        ])
        .env("DATASCOPE_API_PORT", &port_text)
        .env("DATASCOPE_RERUN_PYTHON", &python)
        .env("PYTHONNOUSERSITE", "1")
        .env_remove("PYTHONHOME")
        .env_remove("PYTHONPATH")
        .stdout(Stdio::from(log_file))
        .stderr(Stdio::from(err_file));

    if let Some(dir) = &runtime_dir {
        command.env("DATASCOPE_RUNTIME_DIR", dir);
    }
    prepend_python_to_path(&mut command, &python)?;

    let mut child = command
        .spawn()
        .map_err(|err| format!("could not start DataScope API with {}: {err}", python.display()))?;

    if !wait_for_api(port, Duration::from_secs(30)) {
        let _ = child.kill();
        let _ = child.wait();
        return Err(format!(
            "DataScope API did not become ready on 127.0.0.1:{port}. See {}",
            log_path.display()
        ));
    }

    let rerun_available = runtime_python_has_module(&python, "rerun_cli");
    Ok(BackendState {
        port,
        packaged_runtime,
        runtime_dir,
        rerun_available,
        child: Mutex::new(Some(child)),
    })
}

fn find_runtime_dir(app: &AppHandle) -> Option<PathBuf> {
    if let Ok(path) = env::var("DATASCOPE_RUNTIME_DIR") {
        let dir = PathBuf::from(path);
        if runtime_dir_valid(&dir) {
            return Some(dir);
        }
    }

    let mut candidates = Vec::new();
    if let Ok(resource_dir) = app.path().resource_dir() {
        candidates.push(resource_dir.join("datascope-runtime"));
        candidates.push(resource_dir.join("resources").join("datascope-runtime"));
    }
    candidates.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("resources/datascope-runtime"));

    candidates.into_iter().find(|dir| runtime_dir_valid(dir))
}

fn runtime_dir_valid(dir: &Path) -> bool {
    dir.join("runtime-manifest.json").is_file() && find_runtime_python(dir).is_some()
}

fn find_runtime_python(runtime_dir: &Path) -> Option<PathBuf> {
    let candidates = [
        runtime_dir.join("python/python.exe"),
        runtime_dir.join("python/Scripts/python.exe"),
        runtime_dir.join("python/bin/python3"),
        runtime_dir.join("python/bin/python"),
    ];
    candidates.into_iter().find(|path| path.is_file())
}

fn find_dev_python() -> Option<PathBuf> {
    let repo_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../..")
        .canonicalize()
        .ok()?;
    let candidates = [
        repo_root.join(".venv/Scripts/python.exe"),
        repo_root.join(".venv/bin/python"),
        repo_root.join(".venv/bin/python3"),
    ];
    candidates.into_iter().find(|path| path.is_file())
}

fn reserve_local_port() -> Result<u16, String> {
    let listener = TcpListener::bind("127.0.0.1:0")
        .map_err(|err| format!("could not reserve a local API port: {err}"))?;
    let port = listener
        .local_addr()
        .map_err(|err| format!("could not read reserved local API port: {err}"))?
        .port();
    drop(listener);
    Ok(port)
}

fn wait_for_api(port: u16, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if api_ready(port) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(150));
    }
    false
}

fn api_ready(port: u16) -> bool {
    let request = ApiRequest {
        method: "GET".to_string(),
        path: "/api/health".to_string(),
        body: None,
    };
    perform_api_request(request, port)
        .map(|response| response.status == 200)
        .unwrap_or(false)
}

fn backend_log_path(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_log_dir()
        .or_else(|_| app.path().app_local_data_dir())
        .map_err(|err| format!("could not resolve app log directory: {err}"))?;
    fs::create_dir_all(&dir)
        .map_err(|err| format!("could not create app log directory {}: {err}", dir.display()))?;
    Ok(dir.join("datascope-api.log"))
}

fn prepend_python_to_path(command: &mut Command, python: &Path) -> Result<(), String> {
    let python_dir = python
        .parent()
        .ok_or_else(|| format!("could not resolve Python directory for {}", python.display()))?;
    let mut paths = vec![python_dir.to_path_buf()];
    if let Some(current_path) = env::var_os("PATH") {
        paths.extend(env::split_paths(&current_path));
    }
    let joined = env::join_paths(paths).map_err(|err| format!("could not build PATH: {err}"))?;
    command.env("PATH", joined);
    Ok(())
}

fn runtime_python_has_module(python: &Path, module: &str) -> bool {
    let code = format!(
        "import importlib.util; raise SystemExit(0 if importlib.util.find_spec({module:?}) else 1)"
    );
    let status = Command::new(python)
        .args(["-c", &code])
        .env("PYTHONNOUSERSITE", "1")
        .env_remove("PYTHONHOME")
        .env_remove("PYTHONPATH")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
    status.map(|status| status.success()).unwrap_or(false)
}

fn external_backend_enabled() -> bool {
    matches!(
        env::var("DATASCOPE_DEV_BACKEND").as_deref(),
        Ok("1") | Ok("true") | Ok("TRUE") | Ok("yes") | Ok("YES") | Ok("on") | Ok("ON")
    )
}

fn safe_graphics_enabled() -> bool {
    matches!(
        std::env::var("DATASCOPE_SAFE_GRAPHICS").as_deref(),
        Ok("1") | Ok("true") | Ok("TRUE") | Ok("yes") | Ok("YES") | Ok("on") | Ok("ON")
    )
}

fn configure_webkit_environment() {
    // Keep the low-cost Linux WebKitGTK workarounds by default. The heavier software
    // rendering fallback is opt-in because it makes normal interaction noticeably slower.
    for (key, value) in [
        ("WEBKIT_DISABLE_DMABUF_RENDERER", "1"),
        ("NO_AT_BRIDGE", "1"),
    ] {
        std::env::set_var(key, value);
    }
    if safe_graphics_enabled() {
        for (key, value) in [
            ("WEBKIT_DISABLE_COMPOSITING_MODE", "1"),
            ("WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS", "1"),
            ("LIBGL_ALWAYS_SOFTWARE", "1"),
            ("GSK_RENDERER", "cairo"),
            ("GDK_BACKEND", "x11"),
        ] {
            std::env::set_var(key, value);
        }
    }
}

fn main() {
    configure_webkit_environment();

    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let backend_state = start_backend(app.handle())?;
            app.manage(backend_state);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![api_request, api_status])
        .run(tauri::generate_context!())
        .expect("error while running DataScope Studio");
}
