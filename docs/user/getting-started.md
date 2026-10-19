# Getting started

## Requirements

- **Node.js** 18+ and **Python** 3.10+
- **Rust / Cargo** (desktop builds only)
- System **ffmpeg** on your `PATH` for video scrub / export
  - macOS: `brew install ffmpeg`
  - Windows: install ffmpeg and add it to PATH

## Development (browser)

From the repo root (macOS, Linux, or **native Windows PowerShell** — not WSL):

```bash
npm run dev
```

Creates `./venv` if needed, installs deps, starts the API on port **8765**, Vite on **5173**, and opens the browser.

On Windows this runs `scripts/dev.ps1` (venv at `venv\Scripts\python.exe`). You can also run:

```powershell
.\scripts\dev.ps1
```

Do **not** use WSL for the Windows Tauri / NSIS path — build and run from normal PowerShell.

## Desktop app

The Tauri shell embeds the web UI and starts the Python API from this checkout’s `./venv`. The installer / `.app` alone is not enough — you still need the repo + venv (or set `FPA_ROOT` / `FPA_PYTHON`).

### macOS

```bash
./build_macos.sh          # or: npm run build
./scripts/open-app.sh     # sets FPA_ROOT and opens the .app
```

First Gatekeeper open: Finder → right-click → **Open**.

### Windows

```powershell
.\scripts\build_windows.ps1
.\scripts\open-app.ps1
```

Output is an unsigned NSIS installer under `src-tauri\target\release\bundle\nsis\`. SmartScreen may warn on first run; that is expected for unsigned builds.

**Standalone zip for someone else (no repo needed):** on a Windows machine with the full toolchain, run `.\scripts\pack_windows_portable.ps1` and send the zip from `releases\`. They unzip and run **Start.bat**. No code-signing license required.

## Environment overrides

| Variable | Purpose |
|----------|---------|
| `FPA_ROOT` | Absolute path to this repo (required if the app is not next to the checkout) |
| `FPA_PYTHON` | Absolute path to the Python executable to use for the API |
