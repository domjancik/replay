$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/'
}
Push-Location $projectRoot
try {
    $pythonVersion = (Get-Content -LiteralPath '.python-version' -Raw).Trim()
    & uv python install $pythonVersion
    if ($LASTEXITCODE -ne 0) { throw 'Python installation failed' }
    & uv sync --locked --no-dev --cache-dir artifacts/uv-cache
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
        Write-Warning 'Install FFmpeg with libx264 on PATH before generating videos.'
    }
    Write-Host 'Ready to start: ./scripts/start-replay.ps1'
} finally {
    Pop-Location
}
