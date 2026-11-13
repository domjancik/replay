# Install and run the local preview

## Tested target

Windows, the pinned CPython 3.13 environment and a local browser. The Python wheel is portable in format, but that is not a claim that macOS/Linux, their native kernel builds or their cancellation paths have been release-tested. No installer, signing certificate or auto-update service is provided.

## Source installation (recommended)

1. Install uv from https://docs.astral.sh/uv/getting-started/installation/.
2. Install FFmpeg with `libx264` and make `ffmpeg`/`ffprobe` available on PATH. Install Poppler's `pdftoppm` for PDF comparison or anchored ink. Obtain binaries from sources you trust; they are separate dependencies, not bundled here.
3. Extract the reviewed source archive into a writable folder.
4. Run `./scripts/setup.ps1`. It installs the exact Python pin and synchronizes runtime dependencies from `uv.lock`. This first step requires network access.
5. Run `./scripts/start-replay.ps1`, then open http://127.0.0.1:8765. The launcher uses the installed environment offline.

Keep the server terminal open. Ctrl+C stops it and cancels unfinished work. An occupied port can be changed with `./scripts/start-replay.ps1 -Port 8766`. Do not expose this service through a public reverse proxy or change its loopback binding.

## Wheel installation

A wheel includes the Python package and browser assets, but not the Rust binary or external tools. In a Python 3.13 virtual environment, install the reviewed wheel with pip or uv, then run:

```powershell
rm-redraw --data ./replay-data
```

The wheel's dependency ranges are not a full environment lock. For the exact tested dependency set, use the source release and `uv.lock`. Keep `replay-data` outside any public repository. Paths shown by the server identify where your local imports, native references, frames and videos are saved.

## Optional faster pencil rendering

Install Rust and its platform linker, then follow `native/pencil-kernel/README.md`. The source launcher discovers the Windows checkout build automatically. For an installed wheel, set `RM_REDRAW_PENCIL_LIBRARY` to the absolute path of your own compatible build. Missing or incompatible explicitly selected kernels fail rather than silently changing backend. Python remains available.

## Common problems

- **No uv / missing environment:** run setup first. The launcher does not install packages implicitly.
- **No FFmpeg:** still images can be produced by the renderer API, but the replay utility needs FFmpeg for MP4 generation.
- **USB unavailable:** enable USB web access on the tablet and check its cable. A PDF export timeout may occur even when raw download works; retained attempts are separate from connectivity failures.
- **Anchors unresolved:** attach a PDF exported from the same unchanged notebook, or use an explicitly evidenced anchor layout through the CLI.
- **Scrolling ink is clipped:** inspect canvas size and X/Y offsets; the page's base screen size can be smaller than the full scrolling export. A crop of a finished replay cannot restore ink omitted by the original render.
- **Export is slow:** start at 6 or 12 fps and a small output width. Save the original replay, then reuse its frames for crops/loops. Tall source pages still consume source-resolution memory.
- **Disk usage:** lossless frames are kept for reproducibility and future crop exports. Stop the server before manually moving or deleting a job directory. Back up anything you want to retain.

## Local verification

The release check must inspect both source and wheel contents and smoke-test the installed wheel outside the source tree. The release readiness document records the actual commands and observed platform; a successful package build alone is insufficient.

### Optional USB companion

For USB access through a browser bridge, use the double-clickable Windows companion described in [USB companion setup](usb-companion.md). Cloud pairing and importing existing files remain companion-free. The development build lives in `artifacts/usb-companion/dist/rePlay-USB-Companion.exe`; no terminal or Python installation is needed to run it.
