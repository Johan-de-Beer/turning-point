[CmdletBinding()]
param([switch]$NoInstall, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtimePath = Join-Path $taskRoot '.runtime'
New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null

function Test-LocalHealth([string]$Url) {
    try { return (Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 }
    catch { return $false }
}

Push-Location $taskRoot
try {
    if (-not $NoInstall) {
        if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { python -m venv .venv; if ($LASTEXITCODE) { throw 'Python virtual environment creation failed.' } }
        & '.venv/Scripts/python.exe' -m pip install -r backend/requirements.txt -c backend/requirements.lock.txt
        if ($LASTEXITCODE) { throw 'Backend dependency installation failed.' }
        Push-Location frontend
        try { npm.cmd ci; if ($LASTEXITCODE) { throw 'Frontend dependency installation failed.' } }
        finally { Pop-Location }
    }
    if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { throw 'Run without -NoInstall once to create the virtual environment.' }
    if (Test-LocalHealth 'http://127.0.0.1:8000/api/health') { throw 'Port 8000 is already serving an app. Stop the existing run first (scripts/stop.ps1).' }
    foreach ($port in @(8000, 5173)) {
        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { throw "Port $port is occupied. Stop that app before starting Turning Point." }
    }
    # Local launch is deliberately credential-free and cannot opt into inference.
    $env:PROVIDER = 'mock'
    $env:PUBLIC_DEMO = 'false'
    $env:MICROSOFT_INFERENCE_APPROVED = 'false'
    $env:DATABASE_PATH = Join-Path $runtimePath 'turning-point.sqlite3'
    $env:ALLOWED_ORIGINS = 'http://127.0.0.1:5173,http://localhost:5173'
    $backendProc = Start-Process -FilePath (Join-Path $taskRoot '.venv/Scripts/python.exe') -ArgumentList @('-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8000') -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimePath 'backend.out.log') -RedirectStandardError (Join-Path $runtimePath 'backend.err.log')
    $frontendProc = Start-Process -FilePath 'cmd.exe' -ArgumentList @('/d','/c','npm.cmd run dev') -WorkingDirectory (Join-Path $taskRoot 'frontend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimePath 'frontend.out.log') -RedirectStandardError (Join-Path $runtimePath 'frontend.err.log')
    @{ backend = $backendProc.Id; frontend = $frontendProc.Id; backend_started_at = $backendProc.StartTime.ToUniversalTime().ToString('o'); frontend_started_at = $frontendProc.StartTime.ToUniversalTime().ToString('o'); root = $taskRoot; started_at = (Get-Date).ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtimePath 'processes.json') -Encoding utf8
    $ready = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if ((Test-LocalHealth 'http://127.0.0.1:8000/api/health') -and (Test-LocalHealth 'http://127.0.0.1:5173/')) { $ready = $true; break }
        if ($backendProc.HasExited -or $frontendProc.HasExited) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw 'Startup did not become healthy. Inspect .runtime/backend.err.log and frontend.err.log. Stop with scripts/stop.ps1 before retrying.' }
    Write-Host 'Turning Point is ready at http://127.0.0.1:5173 (mock provider).'
    Write-Host 'Stop both local processes with: powershell -ExecutionPolicy Bypass -File .\scripts\stop.ps1'
    if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:5173' }
} finally { Pop-Location }
