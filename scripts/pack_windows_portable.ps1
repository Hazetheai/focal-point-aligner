# Assemble a portable Windows folder + zip that another machine can unzip and run
# without cloning the repo. Must run on Windows (native PowerShell, not WSL).
#
# Layout (self-contained):
#   FocalPointAligner-portable-vX.Y.Z/
#     Focal Point Aligner.exe   (+ any sibling .dll / resources from the Tauri build)
#     Start.bat                 (double-click this)
#     README.txt
#     aligner_core.py, api/, …  (Python app)
#     venv\                     (fresh Windows venv with requirements.txt)
#
# Usage:
#   .\scripts\pack_windows_portable.ps1
#   .\scripts\pack_windows_portable.ps1 -SkipBuild   # reuse existing Tauri release exe
#   .\scripts\pack_windows_portable.ps1 -SkipVenv    # copy existing .\venv (faster; less relocatable)
#
param(
  [switch]$SkipBuild,
  [switch]$SkipVenv
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Version = (Get-Content (Join-Path $Root "package.json") -Raw | ConvertFrom-Json).version
if (-not $Version) {
  Write-Error "Could not read version from package.json"
}

if (-not $SkipBuild) {
  & (Join-Path $Root "scripts\build_windows.ps1")
}

$ReleaseDir = Join-Path $Root "src-tauri\target\release"
$ExeName = "Focal Point Aligner.exe"
$ExePath = Join-Path $ReleaseDir $ExeName
if (-not (Test-Path $ExePath)) {
  Write-Error "Missing $ExePath — build first with .\scripts\build_windows.ps1"
}

$PortableName = "FocalPointAligner-portable-v$Version"
$OutRoot = Join-Path $Root "releases"
$Dest = Join-Path $OutRoot $PortableName
$ZipPath = Join-Path $OutRoot "$PortableName.zip"

Write-Host "Assembling portable package → $Dest"

if (Test-Path $Dest) {
  Remove-Item -Recurse -Force $Dest
}
New-Item -ItemType Directory -Force -Path $Dest | Out-Null

# Tauri binary + native deps sitting next to it
Copy-Item -Force $ExePath $Dest
Get-ChildItem -Path $ReleaseDir -Filter "*.dll" -File -ErrorAction SilentlyContinue |
  ForEach-Object { Copy-Item -Force $_.FullName $Dest }
foreach ($extra in @("resources", "WebView2Loader.dll")) {
  $p = Join-Path $ReleaseDir $extra
  if (Test-Path $p) {
    Copy-Item -Recurse -Force $p $Dest
  }
}

# Python runtime sources (API + core). Keep this list tight — no tests / web / tauri.
$PyFiles = @(
  "aligner_core.py",
  "arrange_auto.py",
  "batch.py",
  "import_download.py",
  "cli.py",
  "__init__.py",
  "requirements.txt"
)
foreach ($f in $PyFiles) {
  $src = Join-Path $Root $f
  if (Test-Path $src) {
    Copy-Item -Force $src $Dest
  }
}
Copy-Item -Recurse -Force (Join-Path $Root "api") (Join-Path $Dest "api")

# User docs (Help falls back to checkout path; also useful as plain files)
$DocsDest = Join-Path $Dest "docs\user"
New-Item -ItemType Directory -Force -Path $DocsDest | Out-Null
Copy-Item -Force (Join-Path $Root "docs\user\*.md") $DocsDest

# Fresh venv inside the portable folder (recommended) OR copy existing
$DestVenv = Join-Path $Dest "venv"
$DestPython = Join-Path $DestVenv "Scripts\python.exe"

if ($SkipVenv) {
  $SrcVenv = Join-Path $Root "venv"
  if (-not (Test-Path (Join-Path $SrcVenv "Scripts\python.exe"))) {
    Write-Error "No .\venv to copy. Omit -SkipVenv to create one inside the portable folder."
  }
  Write-Host "Copying existing venv (may keep absolute paths in pyvenv.cfg)…"
  Copy-Item -Recurse -Force $SrcVenv $DestVenv
} else {
  Write-Host "Creating portable venv and installing requirements (this can take a few minutes)…"
  $PyCmd = $null
  if (Get-Command python -ErrorAction SilentlyContinue) { $PyCmd = "python" }
  elseif (Get-Command py -ErrorAction SilentlyContinue) { $PyCmd = "py" }
  if (-not $PyCmd) {
    Write-Error "Python not on PATH — needed to create the portable venv."
  }
  & $PyCmd -m venv $DestVenv
  & (Join-Path $DestVenv "Scripts\pip.exe") install -U pip
  & (Join-Path $DestVenv "Scripts\pip.exe") install -r (Join-Path $Dest "requirements.txt")
}

if (-not (Test-Path $DestPython)) {
  Write-Error "Portable venv python missing at $DestPython"
}

# Double-click launcher (sets working directory so discovery finds aligner_core.py + venv)
$StartBat = @"
@echo off
cd /d "%~dp0"
start "" "%~dp0$ExeName"
"@
Set-Content -Path (Join-Path $Dest "Start.bat") -Value $StartBat -Encoding ASCII

$Readme = @"
Focal Point Aligner — portable Windows build v$Version
=====================================================

1. Unzip this folder anywhere (keep the folder together; do not move only the .exe).
2. Double-click Start.bat  (or "Focal Point Aligner.exe").
3. First launch may show SmartScreen ("Windows protected your PC"):
   More info → Run anyway. No code-signing certificate is required.
4. Video scrub / export needs ffmpeg on your PATH
   (https://ffmpeg.org/download.html or winget install ffmpeg).

This package includes the desktop UI, the Python API, and a local venv.
You do NOT need to clone the git repo or run npm.

Optional: install ffmpeg, then reopen the app.

Troubleshooting
- If the window opens but nothing loads, check that venv\Scripts\python.exe exists.
- Depth / Faces AutoArrange may download models into .fpa_models\ on first use.
"@
Set-Content -Path (Join-Path $Dest "README.txt") -Value $Readme -Encoding UTF8

# Zip
if (Test-Path $ZipPath) {
  Remove-Item -Force $ZipPath
}
Write-Host "Zipping → $ZipPath"
Compress-Archive -Path $Dest -DestinationPath $ZipPath -CompressionLevel Optimal

$LatestDir = Join-Path $OutRoot "latest-portable"
if (Test-Path $LatestDir) {
  Remove-Item -Recurse -Force $LatestDir
}
New-Item -ItemType Directory -Force -Path $LatestDir | Out-Null
Copy-Item -Force $ZipPath (Join-Path $LatestDir "$PortableName.zip")

Write-Host ""
Write-Host "Portable folder: $Dest"
Write-Host "Zip to share:    $ZipPath"
Write-Host "Give your collaborator the zip. They unzip and run Start.bat."
