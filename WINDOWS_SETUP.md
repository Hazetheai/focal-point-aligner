# Windows / cross-platform setup

Use **native Windows PowerShell** (not WSL) for both `npm run dev` and the Tauri NSIS build. Full details: **[README.md](README.md)**.

## Quick start (dev UI)

1. Install **Git**, **Node.js 18+**, **Python 3.10+** (check “Add python.exe to PATH”), and **ffmpeg** on PATH for video.
2. Clone the repo, open PowerShell in the repo root.
3. `npm install` then `npm run dev` (runs `scripts/dev.ps1`).

## Desktop (unsigned NSIS)

Also need **Rust**, **MSVC Build Tools** (C++ workload), and **WebView2** (usually already on Win10/11).

```powershell
.\scripts\build_windows.ps1
.\scripts\open-app.ps1
```

The `.exe` / installer still needs this checkout + `.\venv` (or `FPA_ROOT` / `FPA_PYTHON`).

End-user Help: [`docs/user/`](docs/user/).
