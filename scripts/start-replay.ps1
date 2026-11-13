param([ValidateRange(1024,65535)][int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        & uv run --locked --no-sync --no-dev --offline --cache-dir artifacts/uv-cache python -m rm_redraw.web --port $Port
    } else {
        if (-not (Test-Path -LiteralPath "$projectRoot/.venv/Scripts/python.exe")) {
            throw 'Environment missing. Install uv and run ./scripts/setup.ps1 first.'
        }
        & "$projectRoot/.venv/Scripts/python.exe" -m rm_redraw.web --port $Port
    }
    if ($LASTEXITCODE -ne 0) { throw "Replay utility exited with status $LASTEXITCODE" }
} finally {
    Pop-Location
}
