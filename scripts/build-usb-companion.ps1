$ErrorActionPreference = 'Stop'
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    uv run --no-project --python 3.13.15 --with pyinstaller==6.22.0 python -m PyInstaller --noconfirm --clean --onefile --windowed --name rePlay-USB-Companion --paths src --distpath artifacts/usb-companion/dist --workpath artifacts/usb-companion/build --specpath artifacts/usb-companion src/rm_redraw/companion/desktop.py
    if ($LASTEXITCODE -ne 0) { throw 'Companion build failed' }
    Get-FileHash -Algorithm SHA256 artifacts/usb-companion/dist/rePlay-USB-Companion.exe
} finally { Pop-Location }
