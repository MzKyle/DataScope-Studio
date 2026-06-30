mod diagnostic_log;

use std::env;
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
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
    log_dir: String,
    desktop_log_path: String,
    backend_log_path: String,
}

#[derive(serde::Deserialize)]
struct DiagnosticEvent {
    level: String,
    component: String,
    message: String,
    context: Option<serde_json::Value>,
}

struct BackendState {
    port: u16,
    packaged_runtime: bool,
    runtime_dir: Option<PathBuf>,
    rerun_available: bool,
    log_dir: PathBuf,
    desktop_log_path: PathBuf,
    backend_log_path: PathBuf,
    child: Mutex<Option<Child>>,
}

#[derive(Clone, Default)]
struct SmokeState {
    frontend_ready: Arc<AtomicBool>,
}

impl Drop for BackendState {
    fn drop(&mut self) {
        if let Ok(child_slot) = self.child.get_mut() {
            if let Some(mut child) = child_slot.take() {
                let _ = diagnostic_log::write(
                    "info",
                    "desktop.backend",
                    "stopping bundled API process",
                    Some(serde_json::json!({"pid": child.id()})),
                );
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
    let method = request.method.clone();
    let path = request.path.clone();
    let result = tauri::async_runtime::spawn_blocking(move || perform_api_request(request, port))
        .await
        .map_err(|err| format!("API task failed: {err}"))?;
    match &result {
        Ok(response) if response.status >= 400 => {
            let _ = diagnostic_log::write(
                if response.status >= 500 {
                    "error"
                } else {
                    "warn"
                },
                "desktop.api_proxy",
                "local API returned an error response",
                Some(serde_json::json!({
                    "method": method,
                    "path": path,
                    "status": response.status,
                })),
            );
        }
        Err(error) => {
            let _ = diagnostic_log::write(
                "error",
                "desktop.api_proxy",
                error,
                Some(serde_json::json!({"method": method, "path": path})),
            );
        }
        _ => {}
    }
    result
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
        log_dir: state.log_dir.to_string_lossy().to_string(),
        desktop_log_path: state.desktop_log_path.to_string_lossy().to_string(),
        backend_log_path: state.backend_log_path.to_string_lossy().to_string(),
    })
}

#[tauri::command]
fn write_diagnostic_log(
    event: DiagnosticEvent,
    smoke_state: tauri::State<'_, SmokeState>,
) -> Result<(), String> {
    if event.component == "frontend.lifecycle" && event.message == "frontend initialized" {
        smoke_state.frontend_ready.store(true, Ordering::SeqCst);
    }
    diagnostic_log::write(
        &event.level,
        &event.component,
        &event.message,
        event.context,
    )
    .map_err(|error| format!("could not write diagnostic log: {error}"))
}

fn perform_api_request(request: ApiRequest, port: u16) -> Result<ApiResponse, String> {
    let method = request.method.to_uppercase();
    if !api_method_supported(&method) {
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

fn api_method_supported(method: &str) -> bool {
    matches!(method, "GET" | "POST" | "PUT" | "PATCH" | "DELETE")
}

fn start_backend(app: &AppHandle) -> Result<BackendState, String> {
    let log_dir = diagnostic_log::log_dir();
    let desktop_log_path = diagnostic_log::desktop_log_path();
    let backend_log_path = diagnostic_log::backend_log_path();
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
            log_dir,
            desktop_log_path,
            backend_log_path,
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
    let log_path = backend_log_path;
    if let Err(error) = diagnostic_log::rotate_if_needed(&log_path) {
        let _ = diagnostic_log::write(
            "warn",
            "desktop.logging",
            "could not rotate API log",
            Some(serde_json::json!({
                "path": log_path.to_string_lossy(),
                "error": error.to_string(),
            })),
        );
    }
    if let Some(parent) = log_path.parent() {
        fs::create_dir_all(parent).map_err(|err| {
            format!(
                "could not create API log directory {}: {err}",
                parent.display()
            )
        })?;
    }
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

    let mut child = command.spawn().map_err(|err| {
        format!(
            "could not start DataScope API with {}: {err}",
            python.display()
        )
    })?;
    let _ = diagnostic_log::write(
        "info",
        "desktop.backend",
        "started bundled API process",
        Some(serde_json::json!({
            "pid": child.id(),
            "port": port,
            "python": python.to_string_lossy(),
            "packaged_runtime": packaged_runtime,
        })),
    );

    if !wait_for_api(port, Duration::from_secs(30)) {
        let _ = child.kill();
        let _ = child.wait();
        return Err(format!(
            "DataScope API did not become ready on 127.0.0.1:{port}. See {}",
            log_path.display()
        ));
    }

    let rerun_available = runtime_python_has_module(&python, "rerun_cli");
    let _ = diagnostic_log::write(
        "info",
        "desktop.backend",
        "local API is ready",
        Some(serde_json::json!({
            "port": port,
            "rerun_available": rerun_available,
        })),
    );
    Ok(BackendState {
        port,
        packaged_runtime,
        runtime_dir,
        rerun_available,
        log_dir,
        desktop_log_path,
        backend_log_path: log_path,
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

fn wait_for_frontend_ready(smoke_state: &SmokeState, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if smoke_state.frontend_ready.load(Ordering::SeqCst) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    smoke_state.frontend_ready.load(Ordering::SeqCst)
}

fn prepend_python_to_path(command: &mut Command, python: &Path) -> Result<(), String> {
    let python_dir = python.parent().ok_or_else(|| {
        format!(
            "could not resolve Python directory for {}",
            python.display()
        )
    })?;
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

fn smoke_test_requested() -> bool {
    env::args().any(|arg| arg == "--smoke-test")
}

fn main() {
    let desktop_log_path = diagnostic_log::initialize();
    diagnostic_log::install_panic_hook();
    let _ = diagnostic_log::write(
        "info",
        "desktop.lifecycle",
        "DataScope Studio starting",
        Some(serde_json::json!({
            "version": env!("CARGO_PKG_VERSION"),
            "desktop_log_path": desktop_log_path.to_string_lossy(),
            "safe_graphics": safe_graphics_enabled(),
        })),
    );
    configure_webkit_environment();
    let smoke_test = smoke_test_requested();

    let result = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(SmokeState::default())
        .setup(move |app| {
            let _ = diagnostic_log::write("info", "desktop.lifecycle", "Tauri setup started", None);
            let backend_state = start_backend(app.handle()).map_err(|error| {
                let _ = diagnostic_log::write(
                    "error",
                    "desktop.startup",
                    "could not start local API",
                    Some(serde_json::json!({"error": error})),
                );
                error
            })?;
            let smoke_backend_ok = api_ready(backend_state.port)
                && backend_state.packaged_runtime
                && backend_state.runtime_dir.is_some()
                && backend_state.rerun_available;
            let smoke_state = app.state::<SmokeState>().inner().clone();
            app.manage(backend_state);
            if smoke_test {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.hide();
                }
                let handle = app.handle().clone();
                std::thread::spawn(move || {
                    let frontend_ready = wait_for_frontend_ready(
                        &smoke_state,
                        Duration::from_secs(10),
                    );
                    handle.exit(if smoke_backend_ok && frontend_ready { 0 } else { 1 });
                });
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            api_request,
            api_status,
            write_diagnostic_log
        ])
        .run(tauri::generate_context!());
    match result {
        Ok(()) => {
            let _ = diagnostic_log::write(
                "info",
                "desktop.lifecycle",
                "DataScope Studio exited normally",
                None,
            );
        }
        Err(error) => {
            let _ = diagnostic_log::write(
                "error",
                "desktop.startup",
                "desktop runtime exited with an error",
                Some(serde_json::json!({"error": error.to_string()})),
            );
            eprintln!("DataScope Studio failed to start: {error}");
            std::process::exit(1);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::thread;

    fn assert_forwarded(method: &str) {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind test server");
        let port = listener.local_addr().expect("test server address").port();
        let expected = method.to_string();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept request");
            let mut request = Vec::new();
            stream
                .set_read_timeout(Some(Duration::from_secs(2)))
                .expect("set timeout");
            loop {
                let mut chunk = [0_u8; 1024];
                let count = stream.read(&mut chunk).expect("read request");
                if count == 0 {
                    break;
                }
                request.extend_from_slice(&chunk[..count]);
                if request.windows(4).any(|window| window == b"\r\n\r\n") {
                    break;
                }
            }
            let request = String::from_utf8(request).expect("utf8 request");
            assert!(request.starts_with(&format!("{expected} /api/test HTTP/1.1")));
            stream
                .write_all(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 11\r\nConnection: close\r\n\r\n{\"ok\":true}",
                )
                .expect("write response");
        });

        let response = perform_api_request(
            ApiRequest {
                method: method.to_string(),
                path: "/api/test".to_string(),
                body: Some("{}".to_string()),
            },
            port,
        )
        .expect("forward API request");
        assert_eq!(response.status, 200);
        assert_eq!(response.body, "{\"ok\":true}");
        server.join().expect("join test server");
    }

    #[test]
    fn forwards_put_requests() {
        assert_forwarded("PUT");
    }

    #[test]
    fn forwards_delete_requests() {
        assert_forwarded("DELETE");
    }
}
