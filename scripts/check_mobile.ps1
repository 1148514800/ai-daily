<#
.SYNOPSIS
    Run every mobile check a release needs, in order.

.DESCRIPTION
    Runs the type check, the unit tests, and an Android JS bundle export:

        npx tsc --noEmit
        npm test
        npx expo export --platform android

    Nothing here builds or signs an APK, and nothing here changes mobile runtime
    code: it only proves the current code compiles, tests, and bundles.

    The Android SDK is installed at F:\software\Sdk and the JDK at
    F:\software\JDK\jdk-22, but ANDROID_HOME / ANDROID_SDK_ROOT / JAVA_HOME are
    not persisted on this machine. This script sets them for its own process
    only; it does not touch the system environment.

.PARAMETER SkipExport
    Skip the bundle export (the slowest step).

.EXAMPLE
    .\scripts\check_mobile.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipExport
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$mobileDir = Join-Path $repoRoot 'mobile'

if (-not (Test-Path -LiteralPath (Join-Path $mobileDir 'package.json'))) {
    throw "Mobile project not found at $mobileDir."
}

# Process-local only: these paths are the local machine's, and are deliberately
# not written to the user or machine environment.
$androidSdk = 'F:\software\Sdk'
$jdkHome = 'F:\software\JDK\jdk-22'

if (Test-Path -LiteralPath $androidSdk) {
    $env:ANDROID_HOME = $androidSdk
    $env:ANDROID_SDK_ROOT = $androidSdk
}
if (Test-Path -LiteralPath $jdkHome) {
    $env:JAVA_HOME = $jdkHome
}

Push-Location $mobileDir
try {
    Write-Host '== mobile type check ==' -ForegroundColor Cyan
    & npx tsc --noEmit
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Type check failed.' -ForegroundColor Red
        exit $LASTEXITCODE
    }

    Write-Host ''
    Write-Host '== mobile unit tests ==' -ForegroundColor Cyan
    & npm test
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Mobile tests failed.' -ForegroundColor Red
        exit $LASTEXITCODE
    }

    if (-not $SkipExport) {
        Write-Host ''
        Write-Host '== mobile android bundle ==' -ForegroundColor Cyan
        & npx expo export --platform android
        if ($LASTEXITCODE -ne 0) {
            Write-Host 'Bundle export failed.' -ForegroundColor Red
            exit $LASTEXITCODE
        }
    }

    Write-Host ''
    Write-Host 'Mobile checks passed.' -ForegroundColor Green
    exit 0
}
finally {
    Pop-Location
}
