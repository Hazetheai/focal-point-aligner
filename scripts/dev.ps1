# Start the FastAPI backend and Vite web UI together (native Windows / PowerShell).
# Usage from repo root:
#   .\scripts\dev.ps1
#   npm run dev
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$ApiPort = if ($env:FPA_API_PORT) { $env:FPA_API_PORT } else { "8765" }
$WebPort = if ($env:FPA_WEB_PORT) { $env:FPA_WEB_PORT } else { "5173" }

$VenvPython = Join-Path $Root "venv\Scripts\python.exe"
$VenvPip = Join-Path $Root "venv\Scripts\pip.exe"

if (-not (Test-Path $VenvPython)) {
  Write-Host "Creating venv..."
  $PyCmd = $null
  if (Get-Command python -ErrorAction SilentlyContinue) { $PyCmd = "python" }
  elseif (Get-Command py -ErrorAction SilentlyContinue) { $PyCmd = "py" }
  if (-not $PyCmd) {
    Write-Error "Python 3.10+ not found on PATH. Install Python from python.org (check 'Add to PATH') and re-open PowerShell."
  }
  & $PyCmd -m venv (Join-Path $Root "venv")
  if (-not (Test-Path $VenvPip)) {
    Write-Error "venv created but pip missing at $VenvPip"
  }
  & $VenvPip install -U pip
  & $VenvPip install -r (Join-Path $Root "requirements.txt")
}

if (-not (Test-Path (Join-Path $Root "web\node_modules"))) {
  Write-Host "Installing web dependencies..."
  npm --prefix web install
}
if (-not (Test-Path (Join-Path $Root "node_modules"))) {
  npm install
}

function Stop-PortListeners([int]$Port) {
  try {
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  } catch {
    $conns = $null
  }
  if (-not $conns) { return }
  Write-Host "Stopping process(es) on :$Port..."
  $conns | ForEach-Object {
    try { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue } catch {}
  }
  Start-Sleep -Milliseconds 300
}

Stop-PortListeners ([int]$ApiPort)
Write-Host "Starting API on :$ApiPort..."
$env:FPA_API_PORT = "$ApiPort"
$env:FPA_API_RELOAD = "1"
$apiProc = Start-Process -FilePath $VenvPython -ArgumentList @("-m", "api.app") `
  -WorkingDirectory $Root -PassThru -NoNewWindow

$healthy = $false
for ($i = 0; $i -lt 50; $i++) {
  try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$ApiPort/health" -UseBasicParsing -TimeoutSec 1
    if ($r.StatusCode -eq 200) { $healthy = $true; break }
  } catch {}
  if ($apiProc.HasExited) {
    Write-Error "API process exited before becoming healthy."
  }
  Start-Sleep -Milliseconds 100
}
if (-not $healthy) {
  try { Stop-Process -Id $apiProc.Id -Force -ErrorAction SilentlyContinue } catch {}
  Write-Error "API did not start on :$ApiPort"
}

Write-Host "Web UI: http://localhost:$WebPort"
try { Start-Process "http://localhost:$WebPort" } catch {}

try {
  Push-Location (Join-Path $Root "web")
  npm run dev -- --port $WebPort --strictPort
} finally {
  Pop-Location
  if ($apiProc -and -not $apiProc.HasExited) {
    Stop-Process -Id $apiProc.Id -Force -ErrorAction SilentlyContinue
  }
}
