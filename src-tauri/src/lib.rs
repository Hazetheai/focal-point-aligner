use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::Mutex;

use tauri::menu::{Menu, MenuItem, MenuItemKind, HELP_SUBMENU_ID};
use tauri::{Emitter, Manager};

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

    // Walk up from the running executable (Finder / Explorer launches have a useless cwd).
    if let Ok(exe) = std::env::current_exe() {
        let mut cur = exe.parent().map(Path::to_path_buf);
        for _ in 0..10 {
            let Some(dir) = cur else { break };
            if looks_like_project_root(&dir) {
                return dir;
            }
            // Inside .app: .../Contents/MacOS → walk up looking for checkout next to the .app
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
            // Windows NSIS / release exe: check sibling folders of the install or build dir
            #[cfg(windows)]
            {
                if let Some(parent) = dir.parent() {
                    if looks_like_project_root(parent) {
                        return parent.to_path_buf();
                    }
                    for name in ["FocalPointAligner", "focal-point-aligner"] {
                        let candidate = parent.join(name);
                        if looks_like_project_root(&candidate) {
                            return candidate;
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
    } else if cfg!(windows) {
        Err(format!(
            "No project venv at {}. Create it with: python -m venv venv && .\\venv\\Scripts\\pip install -r requirements.txt",
            venv.display()
        ))
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

/// Allowed doc basenames (no path separators).
fn sanitize_doc_name(name: &str) -> Result<String, String> {
    let trimmed = name.trim().trim_start_matches('/');
    if trimmed.is_empty()
        || trimmed.contains("..")
        || trimmed.contains('/')
        || trimmed.contains('\\')
    {
        return Err("invalid doc name".into());
    }
    let base = if trimmed.eq_ignore_ascii_case("index") || trimmed.eq_ignore_ascii_case("readme") {
        "README.md".to_string()
    } else if trimmed.ends_with(".md") {
        trimmed.to_string()
    } else {
        format!("{trimmed}.md")
    };
    Ok(base)
}

fn resolve_user_doc_path(app: &tauri::AppHandle, file_name: &str) -> Result<PathBuf, String> {
    let name = sanitize_doc_name(file_name)?;

    // Bundled resources (macOS Resources / Windows next to exe).
    if let Ok(resource_dir) = app.path().resource_dir() {
        for candidate in [
            resource_dir.join(&name),
            resource_dir.join("docs").join("user").join(&name),
            resource_dir.join("user").join(&name),
        ] {
            if candidate.is_file() {
                return Ok(candidate);
            }
        }
    }

    // Dev / desktop from checkout.
    let root = project_root();
    let checkout = root.join("docs").join("user").join(&name);
    if checkout.is_file() {
        return Ok(checkout);
    }

    Err(format!("User doc not found: {name}"))
}

#[tauri::command]
fn read_user_doc(app: tauri::AppHandle, name: String) -> Result<String, String> {
    let path = resolve_user_doc_path(&app, &name)?;
    fs::read_to_string(&path).map_err(|e| format!("failed to read {}: {e}", path.display()))
}

fn install_help_menu(app: &tauri::AppHandle) -> tauri::Result<()> {
    let menu = Menu::default(app)?;
    let guide = MenuItem::with_id(app, "help-guide", "User Guide", true, None::<&str>)?;
    let keyboard =
        MenuItem::with_id(app, "help-keyboard", "Keyboard Shortcuts", true, None::<&str>)?;
    let troubleshooting =
        MenuItem::with_id(app, "help-troubleshooting", "Troubleshooting", true, None::<&str>)?;
    let about_docs = MenuItem::with_id(app, "help-about", "About Focal Point Aligner", true, None::<&str>)?;

    if let Some(MenuItemKind::Submenu(help)) = menu.get(HELP_SUBMENU_ID) {
        // Prepend so items sit above the platform About entry when present.
        help.prepend_items(&[&guide, &keyboard, &troubleshooting, &about_docs])?;
    } else {
        let help = tauri::menu::Submenu::with_id_and_items(
            app,
            HELP_SUBMENU_ID,
            "Help",
            true,
            &[&guide, &keyboard, &troubleshooting, &about_docs],
        )?;
        menu.append(&help)?;
    }

    app.set_menu(menu)?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![read_user_doc])
        .setup(|app| {
            if let Err(e) = install_help_menu(app.handle()) {
                eprintln!("Focal Point Aligner: failed to install Help menu: {e}");
            }
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
        .on_menu_event(|app, event| {
            let id = event.id().as_ref();
            let page = match id {
                "help-guide" => Some("README.md"),
                "help-keyboard" => Some("keyboard.md"),
                "help-troubleshooting" => Some("troubleshooting.md"),
                "help-about" => Some("about"),
                _ => None,
            };
            if let Some(page) = page {
                let _ = app.emit("open-docs", serde_json::json!({ "page": page }));
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
