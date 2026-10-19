# Copy the latest Windows NSIS installer into releases\ (local unsigned release).
# Version bumps still use scripts/release.sh --bump on macOS, or edit package versions manually.
# Usage:
#   .\scripts\release.ps1
#   .\scripts\release.ps1 -SkipBuild   # copy an already-built NSIS artifact
param(
  [switch]$SkipBuild
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

$NsisDir = Join-Path $Root "src-tauri\target\release\bundle\nsis"
$Installer = Get-ChildItem -Path $NsisDir -Filter "*.exe" -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1

if (-not $Installer) {
  Write-Error "No NSIS installer found under $NsisDir"
}

$DestDir = Join-Path $Root "releases\v$Version"
New-Item -ItemType Directory -Force -Path $DestDir | Out-Null
$Dest = Join-Path $DestDir $Installer.Name
Copy-Item -Force $Installer.FullName $Dest

$Latest = Join-Path $Root "releases\latest"
if (Test-Path $Latest) {
  Remove-Item -Recurse -Force $Latest
}
New-Item -ItemType Directory -Force -Path $Latest | Out-Null
Copy-Item -Force $Dest (Join-Path $Latest $Installer.Name)

# Also stage the bare release exe when present (for open-app.ps1 without installing).
$BareExe = Join-Path $Root "src-tauri\target\release\Focal Point Aligner.exe"
if (Test-Path $BareExe) {
  Copy-Item -Force $BareExe (Join-Path $Latest "Focal Point Aligner.exe")
}

Write-Host "Staged Windows release: $Dest"
Write-Host "Latest: $Latest"
Write-Host "Open with: .\scripts\open-app.ps1 (sets FPA_ROOT)"
