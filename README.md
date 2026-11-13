# rm-redraw

A local reMarkable ink renderer and stroke-replay utility. Import a notebook, choose a page, and export an animated drawing as MP4. Crop a finished replay and add a quick reverse to make a loop without rendering the ink again.

This is an experimental, single-user desktop utility with a browser interface. It runs on your computer; it is not a hosted service and has no cloud integration. Tablet access is read-only.

## Get started

On Windows, install [uv](https://docs.astral.sh/uv/getting-started/installation/) and FFmpeg with H.264 encoding on PATH, then run from the source folder:

```powershell
./scripts/setup.ps1
./scripts/start-replay.ps1
```

Open **http://127.0.0.1:8765**. Import a local `.rmdoc`, or enable the tablet's USB web interface and browse over USB. Saved imports can be replayed without a live tablet connection. This does not establish reference coverage for future renderer calibration.

[Installation, dependencies and troubleshooting](docs/install.md) · [Utility guide](docs/local-replay-utility.md)

## What it supports

- Native v6 scene parsing through `rmscene`, preserving stroke channels and diagnostic unknown data.
- Layer-correct static rendering and smooth directional ink reveal.
- Layer-by-layer or inferred entry order; configurable drawing duration and frame rate.
- Experimental pencil, mechanical-pencil and brush textures, ordinary pens, calligraphy and layer-local erasing.
- Rectangular crop export and forward/reverse loops at 2x, 4x or 8x reverse speed.
- Local comparison against explicitly identified app PNG or tablet PDF references.
- An optional Rust pencil kernel, validated separately against the Python reference on Windows.

## Limits to understand

Replay order and timing are inferred, not recovered wall-clock drawing history. The renderer handles ink, not templates, typed text or PDF/EPUB backgrounds. Text-anchored ink can require a matching native PDF. Scrolling/landscape pages may need explicit canvas dimensions and offsets; base screen metadata does not always describe the full drawing.

Texture profiles are empirical approximations, not the proprietary native algorithm. Close appearance on one drawing is not universal fidelity. PDF export and app PNG export are distinct reference paths. Final forward PNG frames must match static rendering from the same backend/options byte-for-byte; H.264 itself is lossy. Reverse-loop exports intentionally finish at the first frame.

[Calibration development story](docs/calibration-journey.md) · [Renderer landscape](docs/renderer-landscape.md) · [Technical contracts](docs/contracts.md)

## Command line

```powershell
uv run --locked python -m rm_redraw.replay --help
uv run --locked python -m rm_redraw.comparison --help
uv run --locked python -m rm_redraw.parsing --help
```

The installed `rm-redraw` command starts the browser utility; `python -m rm_redraw.web` is equivalent. Use `--data <folder>` to choose a writable local library/output directory. Keep native drawings, PDFs and generated videos private unless you intend to share them.

## Development

Python is pinned in `.python-version`; the dependency graph is pinned in `uv.lock`. CPython has no separately branded LTS channel. Use the pinned interpreter for reproducibility.

```powershell
uv sync --locked --all-groups
uv run --locked pytest
uv run --locked ruff check src tests
```

FFmpeg is required for video tests; Poppler (`pdftoppm`) is required for PDF comparisons and PDF-assisted anchors. Rust is optional: see [kernel build instructions](native/pencil-kernel/README.md). Linux/macOS and browser WASM have not been release-validated.

## Distribution status

The checkout also includes an experimental **Browse cloud** flow using separately installed `rmctl 1.2.0`. It imports one notebook into the existing animation pipeline. An optional stdin-enabled companion supports in-app pairing and explicit revocation, with credentials kept in its local profile. Live account validation remains pending. See the [cloud connector](docs/cloud-connector.md) and [cloud app plan](docs/cloud-app-feasibility.md).

A [browser renderer prototype](docs/wasm-feasibility.md) runs the existing parser, scheduler and renderer in Pyodide. On a small synthetic mixed-tool page, all 29 animation frames and the static frame match desktop Python byte for byte; the browser encodes and plays an MP4 locally. A separate Rust/WASM pencil kernel matches six synthetic masks. These research harnesses are separate from the local app; full-size drawings, browser notebook import, mobile limits and cloud acquisition still need validation.

MIT-licensed code, prepared for a local preview release. Public publication and selected artwork approval remain pending. Do not redistribute the development history or private visual annex as part of a release. See [publication readiness](docs/publication-readiness.md) and [third-party notices](THIRD_PARTY_NOTICES.md). No third-party native binaries or private reference drawings are bundled.
