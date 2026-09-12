<#
.SYNOPSIS
    Remove the AI Daily backend startup task.

.DESCRIPTION
    Unregisters the scheduled task created by install_startup_task.ps1.
    Safe to run when no task exists.

.PARAMETER TaskName
    Name of the scheduled task. Defaults to 'AI Daily Backend'.

.EXAMPLE
    .\scripts\uninstall_startup_task.ps1
#>
[CmdletBinding()]
param(
    [string]$TaskName = 'AI Daily Backend'
)

$ErrorActionPreference = 'Stop'

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "No scheduled task named '$TaskName'. Nothing to remove." -ForegroundColor Yellow
    return
}

if ($task.State -eq 'Running') {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Removed scheduled task: $TaskName" -ForegroundColor Green
