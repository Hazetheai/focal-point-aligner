# Open the release Tauri Windows app with FPA_ROOT pointed at this checkout.
# Prefer a staged local release; fall back to the last Tauri build output.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

$Candidates = @(
  (Join-Path $Root "releases\latest\Focal Point Aligner.exe"),
  (Join-Path $Root "src-tauri\target\release\Focal Point Aligner.exe"),
  (Join-Path $Root "src-tauri\target\release\focal-point-aligner.exe")
)

# Also accept any NSIS-built exe name under bundle\nsis (installer itself is not the app).
$ReleaseExe = $null
foreach ($c in $Candidates) {
  if (Test-Path $c) {
    $ReleaseExe = $c
    break
  }
}

if (-not $ReleaseExe) {
  Write-Error @"
App exe not found.
Build a local release: .\scripts\release.ps1
Or build only: .\scripts\build_windows.ps1
Then install the NSIS package, or run the exe from src-tauri\target\release\
"@
}

$VenvPython = Join-Path $Root "venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
  Write-Error "Missing $VenvPython — create the venv and install requirements.txt"
}

$env:FPA_ROOT = $Root
Write-Host "Opening $ReleaseExe"
Write-Host "FPA_ROOT=$($env:FPA_ROOT)"
Start-Process -FilePath $ReleaseExe
