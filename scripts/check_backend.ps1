<#
.SYNOPSIS
    Run every backend check a release needs, in order.

.DESCRIPTION
    Runs the test suite and then the pre-release check:

        uv run pytest
        uv run python -m app.jobs.release_check

    The release check is read-only: it opens the database read-only, makes no
    RSS or LLM request and changes nothing. It reports PASS / WARN / FAIL and
    exits non-zero on a failure, which is what makes this script safe to gate a
    release on.

.PARAMETER DatabaseUrl
    Database the release check should inspect. Defaults to DATABASE_URL, then to
    the usual backend/data/ai_daily.db.

.PARAMETER SkipTests
    Run only the release check. Useful when the suite was just run.

.EXAMPLE
    .\scripts\check_backend.ps1
#>
[CmdletBinding()]
param(
    [string]$DatabaseUrl,
    [switch]$SkipTests
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

Push-Location $backendDir
try {
    if (-not $SkipTests) {
        Write-Host '== backend tests ==' -ForegroundColor Cyan
        & $uv.Source run pytest
        if ($LASTEXITCODE -ne 0) {
            Write-Host 'Backend tests failed.' -ForegroundColor Red
            exit $LASTEXITCODE
        }
    }

    Write-Host ''
    Write-Host '== backend release check ==' -ForegroundColor Cyan
    $releaseArgs = @('run', 'python', '-m', 'app.jobs.release_check')
    if ($DatabaseUrl) {
        $releaseArgs += @('--database-url', $DatabaseUrl)
    }
    & $uv.Source @releaseArgs
    $code = $LASTEXITCODE

    Write-Host ''
    if ($code -eq 0) {
        Write-Host 'Backend checks passed.' -ForegroundColor Green
    } else {
        Write-Host 'Backend release check failed.' -ForegroundColor Red
    }
    exit $code
}
finally {
    Pop-Location
}
