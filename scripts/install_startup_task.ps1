<#
.SYNOPSIS
    Register the AI Daily backend to start automatically when you log in.

.DESCRIPTION
    Creates a Windows Task Scheduler task that runs scripts/start_backend.ps1 at
    logon for the current user. No administrator rights are required: the task
    runs with a limited token in the user session.

    The task starts a hidden PowerShell window, so logging in does not leave a
    console on screen. Logs still land in logs/backend-<date>.log.

    Safe to run repeatedly: the task is replaced, not duplicated.

.PARAMETER TaskName
    Name of the scheduled task. Defaults to 'AI Daily Backend'.

.PARAMETER Port
    Port passed through to start_backend.ps1.

.EXAMPLE
    .\scripts\install_startup_task.ps1

.NOTES
    Remove the task again with scripts/uninstall_startup_task.ps1
#>
[CmdletBinding()]
param(
    [string]$TaskName = 'AI Daily Backend',
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$startScript = Join-Path $repoRoot 'scripts\start_backend.ps1'

if (-not (Test-Path -LiteralPath $startScript)) {
    throw "start_backend.ps1 not found at $startScript."
}

# Prefer PowerShell 7, but stay compatible with Windows PowerShell 5.1
# (no null-conditional operators here).
$pwshCommand = Get-Command pwsh -ErrorAction SilentlyContinue
if (-not $pwshCommand) {
    $pwshCommand = Get-Command powershell -ErrorAction SilentlyContinue
}
$pwsh = if ($pwshCommand) { $pwshCommand.Source } else { $null }
if (-not $pwsh) {
    throw 'Neither pwsh nor powershell was found on PATH.'
}

$arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$startScript`" -Port $Port"

$action = New-ScheduledTaskAction -Execute $pwsh -Argument $arguments -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Start the AI Daily backend after user logon.' `
    -Force | Out-Null

Write-Host "Startup task registered: $TaskName" -ForegroundColor Green
Write-Host "  runs      : $pwsh $arguments"
Write-Host '  trigger   : at user logon'
Write-Host ''
Write-Host 'Verify with:'
Write-Host "  Get-ScheduledTask -TaskName '$TaskName' | Select-Object TaskName, State"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host ''
Write-Host 'Remove with:'
Write-Host '  .\scripts\uninstall_startup_task.ps1'
