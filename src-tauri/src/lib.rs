use std::path::{Path, PathBuf};
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

fn looks_like_project_root(dir: &Path) -> bool {
    dir.join("aligner_core.py").is_file() && dir.join("api").is_dir()
}

fn project_root() -> PathBuf {
    if let Ok(p) = std::env::var("FPA_ROOT") {
        let root = PathBuf::from(p);
        if looks_like_project_root(&root) {
            return root;
        }
        eprintln!(
            "FPA_ROOT={} does not look like the Focal Point Aligner repo (missing aligner_core.py)",
            root.display()
        );
    }

    // Walk up from the running executable (Finder launches have a useless cwd).
    if let Ok(exe) = std::env::current_exe() {
        let mut cur = exe.parent().map(Path::to_path_buf);
        for _ in 0..8 {
            let Some(dir) = cur else { break };
            // Inside .app: .../Contents/MacOS → walk up looking for checkout next to the .app
            if looks_like_project_root(&dir) {
                return dir;
            }
            // If this is Focal Point Aligner.app/Contents/MacOS, check siblings of the .app
            if dir.ends_with("MacOS") {
                if let Some(contents) = dir.parent() {
                    if let Some(app_bundle) = contents.parent() {
                        if let Some(parent) = app_bundle.parent() {
                            if looks_like_project_root(parent) {
                                return parent.to_path_buf();
                            }
                        }
                    }
                }
            }
            cur = dir.parent().map(Path::to_path_buf);
        }
    }

    let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    if looks_like_project_root(&cwd) {
        return cwd;
    }
    if looks_like_project_root(&cwd.join("..")) {
        return cwd.join("..");
    }
    cwd
}

fn python_bin(root: &Path) -> Result<PathBuf, String> {
    if let Ok(p) = std::env::var("FPA_PYTHON") {
        let bin = PathBuf::from(p);
        if bin.is_file() {
            return Ok(bin);
        }
        return Err(format!("FPA_PYTHON={} is not a file", bin.display()));
    }
    let venv = if cfg!(windows) {
        root.join("venv/Scripts/python.exe")
    } else {
        root.join("venv/bin/python")
    };
    if venv.is_file() {
        Ok(venv)
    } else {
        Err(format!(
            "No project venv at {}. Create it with: python3 -m venv venv && ./venv/bin/pip install -r requirements.txt",
            venv.display()
        ))
    }
}

fn spawn_api() -> Result<Child, String> {
    let root = project_root();
    if !looks_like_project_root(&root) {
        return Err(format!(
            "Could not find project root (aligner_core.py). Set FPA_ROOT to the repo path. Tried: {}",
            root.display()
        ));
    }
    let py = python_bin(&root)?;
    eprintln!(
        "Starting API with {} in {}",
        py.display(),
        root.display()
    );
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
                    eprintln!("Focal Point Aligner: {e}");
                    app.manage(ApiChild(Mutex::new(None)));
                }
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
