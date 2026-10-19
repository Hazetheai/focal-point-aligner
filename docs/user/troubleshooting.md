# Troubleshooting

## API / ports

- Dev API listens on **8765**; Vite on **5173**.
- If the UI cannot reach the API, stop other processes on those ports and run `npm run dev` again (Windows: PowerShell, not WSL).
- Confirm the venv works: `./venv/bin/python -m api.app` (macOS/Linux) or `venv\Scripts\python -m api.app` (Windows).

## Desktop app cannot find the project

The Tauri app expects this checkout + `./venv`.

- Launch via `./scripts/open-app.sh` (macOS) or `.\scripts\open-app.ps1` (Windows), which set `FPA_ROOT`.
- Or set `FPA_ROOT` to the repo path and optionally `FPA_PYTHON` to the venv Python.

## macOS Gatekeeper

Unsigned builds: Finder → right-click the `.app` → **Open** the first time.

## Windows SmartScreen

Unsigned NSIS installers may show “Windows protected your PC”. Use **More info** → **Run anyway** if you built the installer yourself.

## Video / ffmpeg

Export and some codecs need system **ffmpeg** on `PATH`. Install it, reopen the terminal / app, and retry.

## Missing Python packages

```bash
./venv/bin/pip install -r requirements.txt
```

Windows:

```bat
venv\Scripts\pip install -r requirements.txt
```
