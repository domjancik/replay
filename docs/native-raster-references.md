# Native raster reference acquisition

Verified on 2026-09-25: tablet firmware 3.28.0.172; installed desktop app 3.28.1.

## Full-resolution reference

Use the official desktop app's Export as PNG to folder action for a notebook. Preserve original PNG bytes, page order, raw page hashes, app version and export time. The supplied birthday page12 PNG is 1404x1872. Do not reconstruct this target by rasterizing its USB PDF: those export paths differ materially in local tone and texture. The desktop cached page12 .rm is byte-identical to the archived tablet .rm, supporting source correspondence; this does not prove the app export time.

Official workflow: https://support.remarkable.com/articles/Knowledge/Desktop-app

No supported unattended full-resolution PNG route was established in this investigation. GUI batch export is the verified full-resolution mechanism; do not claim a headless exporter exists.

## Automated low-resolution cross-check

Existing device-generated page rasters can be read over SSH from:

```
/home/root/.local/share/remarkable/xochitl/<document UUID>.thumbnails/<page UUID>.png
```

Copy only the selected notebook's cache into an ignored capture directory; match filenames to CRDT-index page order from its raw .content and verify SHA256 against device-side hashes. Never force cache regeneration by rewriting existing documents or restarting xochitl. Cache timestamps can predate the current source state, so record freshness as unproven unless independently established. Do not upscale thumbnails and treat them as full-resolution texture evidence.

All 21 birthday notebook PNGs were acquired and verified, each384x512. At that common size, page12 mean absolute RGB error against the app PNG area-downsample is6.98 for the tablet cache versus27.78 for the full-resolution USB PDF raster area-downsample. The cache visibly preserves the app's shading distribution. The local desktop cache under `%APPDATA%/remarkable/desktop/<document UUID>.thumbnails/` is also384x512; its page12 error is7.14. These are useful tonal references, not pinhole/antialias calibration.

## Routes checked

- Live USB client advertises PDF and rmdoc only. GET `/download/<document UUID>/png` returns HTTP400, `Filetype not supported`. Historical PNG-route documentation is not applicable to this firmware.
- The HTTP thumbnail request timed out after10seconds. This is not proof that thumbnails are unavailable; direct read-only SSH access to existing files succeeded.
- USB PDF via Poppler Splash/Cairo remains a separate vector-export target. Both produce substantially different local shading from the app PNG. Missing GSa state and exact export-renderer differences remain unresolved; do not invent a graphics state or apply arbitrary levels corrections.
- Desktop cache provides direct raster access but no higher-resolution page12 equivalent was found in the inspected notebook cache.

Private evidence: `fixtures/private/masha-native-raster-cache-20260925/manifest.json`, device hashes alongside; `artifacts/reference-audit-20260925/cached-raster-report.json`, `cached-raster-comparison.png`, `desktop-cache-check.json`, and saved USB client/response. Existing tablet documents were not modified.

## Combined export notebook

Prepared `fixtures/private/reference-export-book-20260925/reference-book.rmdoc`, named `RM-REDRAW-ALL-REFERENCES-20260925`. It contains31pages: renderer controls1–19, tap/eraser supplement20–22, pressure/angle controls23–30, and birthday originalpage12 as exportpage31. `PAGE-INDEX.md` and `manifest.json` alongside map every export page to its source archive/page UUID/hash.

All31 raw .rm payloads are byte-identical to the saved sources, parse successfully, and retain per-page metadata/templates. The archive has33members, passes ZIP CRC and ordering checks, and rebuilds deterministically. No cover page or labels were inserted into the stroke data. The ignored `build.py` and `test_bundle.py` reproduce and verify the package. Import/raw-readback and app PNG export validation remain pending: SSH responded, but two permitted USB folder-list requests timed out before any upload was issued. No existing document was changed and no service was restarted. After importing this new notebook, export the whole notebook as PNG to one folder; expect31images and retain their original sizes, including extended eraser pages. This prepared package does not yet establish app-export fidelity or on-device readiness.
