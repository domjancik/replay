param([ValidateRange(1024,65535)][int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        & uv run --locked --offline --cache-dir artifacts/uv-cache python -m rm_redraw.web --port $Port
    } else {
        & "$projectRoot/.venv/Scripts/python.exe" -m rm_redraw.web --port $Port
    }
} finally {
    Pop-Location
}
