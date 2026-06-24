use std::backtrace::Backtrace;
use std::env;
use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

use serde::Serialize;
use serde_json::{json, Value};

const MAX_LOG_BYTES: u64 = 2 * 1024 * 1024;
const LOG_BACKUPS: usize = 3;
const MAX_MESSAGE_CHARS: usize = 4_000;
const MAX_CONTEXT_BYTES: usize = 16 * 1024;
const APP_IDENTIFIER: &str = "studio.datascope.desktop";
const DESKTOP_LOG_NAME: &str = "datascope-studio.log";
const BACKEND_LOG_NAME: &str = "datascope-api.log";

static LOG_WRITE_LOCK: Mutex<()> = Mutex::new(());

#[derive(Serialize)]
struct LogRecord<'a> {
    timestamp_unix_ms: u128,
    level: &'a str,
    component: &'a str,
    message: &'a str,
    pid: u32,
    context: Option<Value>,
}

pub fn initialize() -> PathBuf {
    let path = desktop_log_path();
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let _ = rotate_if_needed(&path);
    path
}

pub fn install_panic_hook() {
    let previous = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |panic_info| {
        let message = if let Some(value) = panic_info.payload().downcast_ref::<&str>() {
            (*value).to_string()
        } else if let Some(value) = panic_info.payload().downcast_ref::<String>() {
            value.clone()
        } else {
            "non-string panic payload".to_string()
        };
        let location = panic_info
            .location()
            .map(|value| format!("{}:{}:{}", value.file(), value.line(), value.column()));
        let thread_name = std::thread::current().name().map(str::to_string);
        let _ = write(
            "error",
            "desktop.panic",
            &message,
            Some(json!({
                "location": location,
                "thread": thread_name,
                "backtrace": Backtrace::force_capture().to_string(),
            })),
        );
        previous(panic_info);
    }));
}

pub fn log_dir() -> PathBuf {
    if let Some(path) = env::var_os("DATASCOPE_LOG_DIR") {
        return PathBuf::from(path);
    }
    platform_log_dir()
}

pub fn desktop_log_path() -> PathBuf {
    log_dir().join(DESKTOP_LOG_NAME)
}

pub fn backend_log_path() -> PathBuf {
    log_dir().join(BACKEND_LOG_NAME)
}

pub fn write(
    level: &str,
    component: &str,
    message: &str,
    context: Option<Value>,
) -> io::Result<()> {
    let _guard = LOG_WRITE_LOCK
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    let path = desktop_log_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    rotate_if_needed(&path)?;
    append_record(&path, level, component, message, context)
}

fn append_record(
    path: &Path,
    level: &str,
    component: &str,
    message: &str,
    context: Option<Value>,
) -> io::Result<()> {
    let level = normalized_level(level);
    let component = truncate(component, 100);
    let message = truncate(message, MAX_MESSAGE_CHARS);
    let context = bounded_context(context);
    let record = LogRecord {
        timestamp_unix_ms: SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis(),
        level,
        component: &component,
        message: &message,
        pid: std::process::id(),
        context,
    };
    let mut line = serde_json::to_vec(&record)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    line.push(b'\n');
    OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)?
        .write_all(&line)
}

pub fn rotate_if_needed(path: &Path) -> io::Result<()> {
    if path.metadata().map(|meta| meta.len()).unwrap_or(0) < MAX_LOG_BYTES {
        return Ok(());
    }
    rotate(path)
}

pub fn rotate(path: &Path) -> io::Result<()> {
    let oldest = backup_path(path, LOG_BACKUPS);
    if oldest.exists() {
        fs::remove_file(oldest)?;
    }
    for index in (1..LOG_BACKUPS).rev() {
        let source = backup_path(path, index);
        if source.exists() {
            fs::rename(source, backup_path(path, index + 1))?;
        }
    }
    if path.exists() {
        fs::rename(path, backup_path(path, 1))?;
    }
    Ok(())
}

fn platform_log_dir() -> PathBuf {
    #[cfg(target_os = "windows")]
    {
        if let Some(root) = env::var_os("LOCALAPPDATA").or_else(|| env::var_os("APPDATA")) {
            return PathBuf::from(root).join(APP_IDENTIFIER).join("logs");
        }
    }
    #[cfg(target_os = "macos")]
    {
        if let Some(home) = env::var_os("HOME") {
            return PathBuf::from(home)
                .join("Library")
                .join("Logs")
                .join(APP_IDENTIFIER);
        }
    }
    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        if let Some(root) = env::var_os("XDG_DATA_HOME") {
            return PathBuf::from(root).join(APP_IDENTIFIER).join("logs");
        }
        if let Some(home) = env::var_os("HOME") {
            return PathBuf::from(home)
                .join(".local")
                .join("share")
                .join(APP_IDENTIFIER)
                .join("logs");
        }
    }
    env::temp_dir().join(APP_IDENTIFIER).join("logs")
}

fn normalized_level(level: &str) -> &str {
    match level.to_ascii_lowercase().as_str() {
        "debug" => "debug",
        "warn" | "warning" => "warn",
        "error" => "error",
        _ => "info",
    }
}

fn bounded_context(context: Option<Value>) -> Option<Value> {
    context.map(|value| {
        let size = serde_json::to_vec(&value)
            .map(|bytes| bytes.len())
            .unwrap_or(0);
        if size > MAX_CONTEXT_BYTES {
            json!({"truncated": true, "original_bytes": size})
        } else {
            value
        }
    })
}

fn truncate(value: &str, max_chars: usize) -> String {
    if value.chars().count() <= max_chars {
        return value.to_string();
    }
    let mut result = value.chars().take(max_chars).collect::<String>();
    result.push_str("…");
    result
}

fn backup_path(path: &Path, index: usize) -> PathBuf {
    PathBuf::from(format!("{}.{}", path.display(), index))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rotates_log_files_and_keeps_numbered_history() {
        let root = env::temp_dir().join(format!(
            "datascope-log-test-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos()
        ));
        fs::create_dir_all(&root).expect("create test directory");
        let path = root.join("desktop.log");
        fs::write(&path, b"current").expect("write current");
        fs::write(backup_path(&path, 1), b"previous").expect("write backup");

        rotate(&path).expect("rotate logs");

        assert!(!path.exists());
        assert_eq!(
            fs::read(backup_path(&path, 1)).expect("read first"),
            b"current"
        );
        assert_eq!(
            fs::read(backup_path(&path, 2)).expect("read second"),
            b"previous"
        );
        fs::remove_dir_all(root).expect("remove test directory");
    }

    #[test]
    fn truncates_large_contexts() {
        let value = bounded_context(Some(json!({"payload": "x".repeat(MAX_CONTEXT_BYTES)})))
            .expect("bounded context");
        assert_eq!(value["truncated"], true);
    }

    #[test]
    fn writes_parseable_json_lines() {
        let root = env::temp_dir().join(format!(
            "datascope-log-json-test-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos()
        ));
        fs::create_dir_all(&root).expect("create test directory");
        let path = root.join("desktop.log");

        append_record(
            &path,
            "warning",
            "frontend.file",
            "could not open file",
            Some(json!({"path": "/tmp/missing.ply"})),
        )
        .expect("write log");

        let line = fs::read_to_string(&path).expect("read log");
        let record: Value = serde_json::from_str(line.trim()).expect("parse log");
        assert_eq!(record["level"], "warn");
        assert_eq!(record["component"], "frontend.file");
        assert_eq!(record["context"]["path"], "/tmp/missing.ply");
        assert!(record["timestamp_unix_ms"].as_u64().is_some());
        fs::remove_dir_all(root).expect("remove test directory");
    }
}
