<#
.SYNOPSIS
    Back up the AI Daily SQLite database.

.DESCRIPTION
    Copies backend/data/ai_daily.db to backups/ai_daily_<timestamp>.db.

    This is a single-user SQLite file with short writes, so a plain copy is
    sufficient here. No destructive operation is performed against the live file.

.PARAMETER Keep
    How many recent backups to keep. Older ones are removed after a successful
    copy. Defaults to 14. Use 0 to keep every backup.

.EXAMPLE
    .\scripts\backup_db.ps1
#>
[CmdletBinding()]
param(
    [int]$Keep = 14
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$source = Join-Path $repoRoot 'backend\data\ai_daily.db'
$backupDir = Join-Path $repoRoot 'backups'

if (-not (Test-Path -LiteralPath $source)) {
    throw "Database not found at $source. Start the backend once so it creates the file."
}

New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$target = Join-Path $backupDir ("ai_daily_{0}.db" -f $stamp)
Copy-Item -LiteralPath $source -Destination $target -Force

$sourceSize = [math]::Round((Get-Item -LiteralPath $source).Length / 1KB, 1)
Write-Host "Backup created: $target ($sourceSize KB)" -ForegroundColor Green

if ($Keep -gt 0) {
    $old = Get-ChildItem -LiteralPath $backupDir -Filter 'ai_daily_*.db' |
        Sort-Object LastWriteTime -Descending |
        Select-Object -Skip $Keep
    foreach ($file in $old) {
        Remove-Item -LiteralPath $file.FullName -Force
        Write-Host "  pruned: $($file.Name)"
    }
}
