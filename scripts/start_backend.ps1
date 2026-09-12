<#
.SYNOPSIS
    Start the AI Daily backend for long-running local use.

.DESCRIPTION
    Runs Uvicorn in production mode: no --reload, a single worker, and a listener
    on all interfaces so the phone can reach it over the LAN.

    A single worker is required because the daily refresh scheduler lives inside
    the process. Several workers would each start their own scheduler and run the
    same job more than once.

    Logs are appended to logs/backend-<date>.log so an unattended start can be
    diagnosed later.

.PARAMETER Port
    TCP port to listen on. Defaults to 8000.

.PARAMETER BindHost
    Interface to bind. Defaults to 0.0.0.0 (LAN reachable).

.EXAMPLE
    .\scripts\start_backend.ps1
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [string]$BindHost = '0.0.0.0'
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $repoRoot 'backend'

if (-not (Test-Path -LiteralPath (Join-Path $backendDir 'app\main.py'))) {
    throw "Backend not found at $backendDir."
}

$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    throw 'uv not found on PATH. Install it from https://docs.astral.sh/uv/ and reopen the terminal.'
}

$logDir = Join-Path $repoRoot 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("backend-{0}.log" -f (Get-Date -Format 'yyyyMMdd'))

Write-Host 'AI Daily backend' -ForegroundColor Cyan
Write-Host "  directory : $backendDir"
Write-Host "  listening : http://${BindHost}:$Port"
Write-Host "  health    : http://127.0.0.1:$Port/health"
Write-Host "  log       : $logFile"

Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
    ForEach-Object { Write-Host "  phone URL : http://$($_.IPAddress):$Port" -ForegroundColor Green }
Write-Host ''

Push-Location $backendDir
try {
    # Single worker on purpose: the in-process APScheduler must not be duplicated.
    & $uv.Source run uvicorn app.main:app --host $BindHost --port $Port 2>&1 |
        Tee-Object -FilePath $logFile -Append
}
finally {
    Pop-Location
}
