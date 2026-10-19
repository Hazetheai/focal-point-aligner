# Open the release Tauri Windows app with FPA_ROOT pointed at this checkout.
# Prefer a staged local release; fall back to the last Tauri build output.
# -Quiet: no console status / API wait (used by Desktop / Start Menu shortcuts).
param(
  [switch]$Quiet
)

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
  Write-Error "Missing $VenvPython. Create the venv and install requirements.txt"
}

# Stale API processes leave port 8765 taken; the next launch then fails silently.
function Stop-FpaApiOnPort {
  param([int]$Port = 8765)
  $conns = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
  foreach ($conn in $conns) {
    $procId = $conn.OwningProcess
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if (-not $proc) { continue }
    $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue).CommandLine
    if ($proc.ProcessName -eq "python" -or ($cmd -and $cmd -like "*api.app*")) {
      if (-not $Quiet) {
        Write-Host "Stopping leftover API pid $procId on port $Port"
      }
      Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
  }
  $deadline = (Get-Date).AddSeconds(5)
  do {
    $still = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if ($still.Count -eq 0) { return }
    Start-Sleep -Milliseconds 200
  } while ((Get-Date) -lt $deadline)
  if (-not $Quiet) {
    Write-Warning "Port $Port is still in use; the app API may fail to bind. Close other Focal Point Aligner / python API processes and retry."
  }
}

Stop-FpaApiOnPort

$env:FPA_ROOT = $Root
if (-not $Quiet) {
  Write-Host "Opening $ReleaseExe"
  Write-Host "FPA_ROOT=$($env:FPA_ROOT)"
}

# Start-Process inherits this session env (including FPA_ROOT).
$app = Start-Process -FilePath $ReleaseExe -PassThru -WorkingDirectory $Root

if ($Quiet) {
  return
}

$log = Join-Path $Root "fpa-api.log"
$deadline = (Get-Date).AddSeconds(20)
$ready = $false
do {
  Start-Sleep -Milliseconds 500
  try {
    $null = Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 "http://127.0.0.1:8765/docs"
    $ready = $true
  } catch {}
} while (-not $ready -and (Get-Date) -lt $deadline)

if ($ready) {
  Write-Host "API ready on http://127.0.0.1:8765"
} else {
  Write-Warning "API did not become ready. Check $log"
  if (Test-Path $log) {
    Write-Host "---- last log lines ----"
    Get-Content $log -Tail 40
  }
  if ($app -and -not $app.HasExited) {
    Write-Warning "App process is running (pid $($app.Id)) but the UI may show a connection error until the API starts."
  }
}
