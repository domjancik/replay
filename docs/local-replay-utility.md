# Local replay utility

Run from this checkout:

```powershell
./scripts/start-replay.ps1
```

Then open **http://127.0.0.1:8765**. Keep the terminal open; Ctrl+C stops the service and cancels unfinished jobs. The script prefers the existing locked uv environment. Alternatively run `.venv/Scripts/python.exe -m rm_redraw.web`. No new Python or JavaScript dependencies are required. FFmpeg must be on PATH; Poppler is needed for PDF-assisted anchors. Build the optional Rust kernel using its README to enable faster pencil rendering. The UI selects Rust when the built library passes its ABI check, otherwise Python; an explicit Rust job never silently falls back.

1. **Browse tablet**: enable its USB web interface, connect its cable, and choose a notebook. Only reads are performed. Two raw exports must have identical member hashes. Optional paired PDF export happens between these reads. A USB timeout does not mean the cable is disconnected; raw-only import can still work when native PDF generation fails. Partial attempts are preserved.
2. Or **Import .rmdoc** from a local file. Copies are immutable. For pages with unresolved text anchors, use **Attach matching PDF**, or import from USB with the PDF checkbox enabled. A manually attached PDF is user-supplied pairing evidence; page-count validation alone does not prove matching content. Anchor matching still rejects weak/ambiguous placements.
3. Choose a page, duration, frame rate, replay ordering and output width. **Layer by layer** finishes each visible layer bottom to top. **Entry order** follows the inferred global entry sequence across visible layers; it does not claim verified drawing chronology. Page numbers follow recorded notebook order; blank/missing-stroke pages keep their slots and cannot be rendered. The canvas preset is explicitly manual: 1404×1872 with a +702 X offset. Source page dimensions populate the controls when available. Adjust canvas and offsets for other devices, landscape or scrolling pages; geometry is not universally inferred. Rendering covers supported ink, not PDF/EPUB backgrounds, templates or typed text.
4. Generate, watch frame progress, then play or download MP4 and final PNG. Multiple submissions queue sequentially. Cancel stops the selected local job; partial output is kept. Completed runs and their manifests survive a service restart.

The fixed-duration schedule samples a synthesized equal-time-per-stroke timeline. Dense drawings can complete several strokes between video frames; sparse drawings show partial directional reveal. Visual layer compositing remains bottom-to-top in either replay ordering, and the final PNG is verified against static rendering before success. The requested duration covers drawing; one second is added for the final hold. Duration is rounded up to the frame interval. Higher frame rates and full-resolution outputs cost more time/disk space; pencil pages can take minutes even for short videos.

All local data defaults to ignored `artifacts/replay-workbench/`:

- `library/`: imported raw notebooks, optional PDFs, hashes and acquisition provenance.
- `import-attempts/`: successful and failed USB read evidence; retained for diagnosis.
- `jobs/<id>/`: job state/log plus `output/{frames,static.png,replay.mp4,manifest.json}`.

Only this loopback address is accepted. The service checks Host, Origin and a per-process local session/token, does not enable CORS, accepts only bounded uploads, and serves an allowlist of generated media with byte-range support. USB requests target only `10.11.99.1`, reject redirects, bypass HTTP proxies and are serialized. There is no generic URL proxy, arbitrary filesystem browser, tablet write endpoint, cloud integration or network deployment configuration. This is a single-user local utility, not a production web service.

To seed a notebook from the command line, append `--import path/to/notebook.rmdoc` once. Restart without that argument to reuse the saved library. `--port` and `--data` override the port and local data directory; keep private data under ignored paths.

## Validation

Tests cover recorded page ordering/blank slots, archive traversal rejection, stable USB reads and retained failures, bounded replay settings, local-origin/session guards, media ranges, actual CLI job completion and persisted history. The browser smoke test browsed the live tablet, imported the three-page tap-control notebook through two stable raw reads, and generated a control replay. The optional PDF export of that notebook timed out, with the raw read retained; this is recorded separately from successful raw import. Birthday page 12 completed through the duration UI: 156 frames, 702x936 at 12 fps, 13 seconds including the hold, in 284 seconds. Its final RGBA pixels exactly match the accepted static golden, and final/static PNG bytes match. The USB-imported control replay contains 42 frames at 6 fps (7 seconds). FFprobe verified both encoded durations. Browser playback was inspected. Evidence remains under ignored `artifacts/replay-workbench/validation.json`.

On a completed original replay, choose **Crop / loop export**. Drag a rectangle over the final image or enter pixel bounds; **Reset to full page** removes the crop. Choose forward only, or forward followed by 2x, 4x (default), or 8x reverse. Export reuses saved lossless frames without rendering the ink again. Bounds snap to even pixels for H.264. Each export is a separate history item; use the original replay to try another crop. The forward ending retains its hold; reverse skips that hold and returns to the first frame. The browser player loops; downloaded MP4s contain one forward/reverse cycle.
