# Build the unsigned Tauri Windows NSIS installer (React UI + Python API via project .\venv).
# Run from the repo root in PowerShell:
#   .\scripts\build_windows.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$VenvPython = Join-Path $Root "venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
  Write-Host "Create .\venv first:"
  Write-Host "  python -m venv venv"
  Write-Host "  .\venv\Scripts\pip install -r requirements.txt"
  exit 1
}

if (-not (Test-Path (Join-Path $Root "web\node_modules"))) {
  npm --prefix web install
}
if (-not (Test-Path (Join-Path $Root "node_modules"))) {
  npm install
}

# Ensure cargo is on PATH when installed via rustup
$CargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
if (Test-Path $CargoBin) {
  $env:Path = "$CargoBin;$env:Path"
}

# Keep Vite public docs in sync with canonical docs/user
$DocsSrc = Join-Path $Root "docs\user"
$DocsDst = Join-Path $Root "web\public\docs\user"
New-Item -ItemType Directory -Force -Path $DocsDst | Out-Null
Copy-Item -Force (Join-Path $DocsSrc "*.md") $DocsDst

npm run build

$NsisDir = Join-Path $Root "src-tauri\target\release\bundle\nsis"
Write-Host ""
Write-Host "NSIS output folder: $NsisDir"
Get-ChildItem -Path $NsisDir -Filter "*.exe" -ErrorAction SilentlyContinue | ForEach-Object {
  Write-Host "Installer: $($_.FullName)"
}
Write-Host "Unsigned: SmartScreen may warn on first run."
Write-Host "Needs this checkout + .\venv (or set FPA_ROOT / FPA_PYTHON)."
Write-Host "Quick launch: .\scripts\open-app.ps1"
