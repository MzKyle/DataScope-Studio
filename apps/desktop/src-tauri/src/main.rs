use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::time::Duration;

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

#[tauri::command]
async fn api_request(request: ApiRequest) -> Result<ApiResponse, String> {
    tauri::async_runtime::spawn_blocking(move || perform_api_request(request))
        .await
        .map_err(|err| format!("API task failed: {err}"))?
}

fn perform_api_request(request: ApiRequest) -> Result<ApiResponse, String> {
    let method = request.method.to_uppercase();
    if !matches!(method.as_str(), "GET" | "POST" | "PATCH") {
        return Err(format!("unsupported API method: {method}"));
    }
    if !request.path.starts_with("/api/") || request.path.contains('\r') || request.path.contains('\n') {
        return Err("unsupported API path".to_string());
    }

    let body = request.body.unwrap_or_default();
    let address: SocketAddr = "127.0.0.1:8000"
        .parse()
        .map_err(|err| format!("invalid API address: {err}"))?;
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_secs(3))
        .map_err(|err| format!("could not reach DataScope API: {err}"))?;
    stream
        .set_read_timeout(Some(Duration::from_secs(20)))
        .map_err(|err| format!("could not set API read timeout: {err}"))?;
    stream
        .set_write_timeout(Some(Duration::from_secs(10)))
        .map_err(|err| format!("could not set API write timeout: {err}"))?;

    let request_text = format!(
        "{method} {} HTTP/1.1\r\nHost: 127.0.0.1:8000\r\nAccept: application/json\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
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
        .invoke_handler(tauri::generate_handler![api_request])
        .run(tauri::generate_context!())
        .expect("error while running DataScope Studio");
}
