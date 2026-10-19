# Create Desktop and/or Start Menu shortcuts that launch via open-app.ps1
# (sets FPA_ROOT so the Python API can start). Re-run after moving the repo.
#
#   .\scripts\create-shortcuts.ps1
#   .\scripts\create-shortcuts.ps1 -DesktopOnly
#   .\scripts\create-shortcuts.ps1 -StartMenuOnly
param(
  [switch]$DesktopOnly,
  [switch]$StartMenuOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$OpenApp = Join-Path $Root "scripts\open-app.ps1"
if (-not (Test-Path $OpenApp)) {
  Write-Error "Missing $OpenApp"
}

$Icon = Join-Path $Root "src-tauri\icons\icon.ico"
if (-not (Test-Path $Icon)) {
  $Icon = Join-Path $Root "src-tauri\target\release\focal-point-aligner.exe"
}

$doDesktop = -not $StartMenuOnly
$doStartMenu = -not $DesktopOnly
$paths = @()

if ($doDesktop) {
  $paths += (Join-Path ([Environment]::GetFolderPath("Desktop")) "Focal Point Aligner.lnk")
}
if ($doStartMenu) {
  $programs = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
  $paths += (Join-Path $programs "Focal Point Aligner.lnk")
}

$shell = New-Object -ComObject WScript.Shell
$ps = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$args = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$OpenApp`" -Quiet"

foreach ($lnkPath in $paths) {
  $shortcut = $shell.CreateShortcut($lnkPath)
  $shortcut.TargetPath = $ps
  $shortcut.Arguments = $args
  $shortcut.WorkingDirectory = $Root
  $shortcut.WindowStyle = 7  # minimized (hidden PowerShell)
  $shortcut.Description = "Focal Point Aligner (sets FPA_ROOT for this checkout)"
  if (Test-Path $Icon) {
    $shortcut.IconLocation = "$Icon,0"
  }
  $shortcut.Save()
  Write-Host "Created $lnkPath"
}

Write-Host "Done. Pin from the Start Menu or Desktop like any other app."
Write-Host "Re-run this script if you move the repo folder."
