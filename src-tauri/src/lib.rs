use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;

use tauri::Manager;

struct ApiChild(Mutex<Option<Child>>);

impl Drop for ApiChild {
    fn drop(&mut self) {
        if let Ok(mut guard) = self.0.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.kill();
            }
        }
    }
}

fn project_root() -> PathBuf {
    if let Ok(p) = std::env::var("FPA_ROOT") {
        return PathBuf::from(p);
    }
    let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    if cwd.join("aligner_core.py").exists() {
        return cwd;
    }
    if cwd.join("../aligner_core.py").exists() {
        return cwd.join("..");
    }
    cwd
}

fn python_bin(root: &PathBuf) -> PathBuf {
    if let Ok(p) = std::env::var("FPA_PYTHON") {
        return PathBuf::from(p);
    }
    let venv = if cfg!(windows) {
        root.join("venv/Scripts/python.exe")
    } else {
        root.join("venv/bin/python")
    };
    if venv.exists() {
        venv
    } else {
        PathBuf::from("python3")
    }
}

fn spawn_api() -> Result<Child, String> {
    let root = project_root();
    let py = python_bin(&root);
    Command::new(py)
        .current_dir(&root)
        .args(["-m", "api.app"])
        .env("FPA_API_PORT", "8765")
        .spawn()
        .map_err(|e| format!("failed to start API: {e}"))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            match spawn_api() {
                Ok(child) => {
                    app.manage(ApiChild(Mutex::new(Some(child))));
                }
                Err(e) => {
                    eprintln!("{e}");
                    app.manage(ApiChild(Mutex::new(None)));
                }
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
