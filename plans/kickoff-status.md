# Kickoff status — 2026-09-05

## Environment and repository

- Local Git repository on `main`; scaffold commit `979dcf0`, Python correction commit `469cc59`.
- uv `0.12.10`; exact CPython `3.13.15`; dependencies locked in `uv.lock`.
- Python 3.13 is a current CPython maintenance/bugfix branch, scheduled for later security-only support and end of life in October 2029. It is not a separately branded LTS release.
- Main parser baseline is `rmscene==0.8.0`. `rmc==0.3.0` was excluded because it requires `rmscene>=0.6,<0.7`.
- Private raw/native device material and generated render/video output are ignored by Git.

## Dispatched work and verified results

| Work | Model | Result |
| --- | --- | --- |
| Acquisition | GPT-5.6 Terra, medium; bounded final verification retried on Sol, medium after Terra capacity failures | SSH source, immutable manifests, stability checks, paired USB/PDF fixture |
| Parser | GPT-5.6 Sol, high | v6 `rmscene` adapter, lossless normalized metadata exposed by the library, cumulative anchored-group transforms, five-page native-PDF anchor calibration, diagnostics and CLI |
| Baseline replay | GPT-5.6 Terra, high | Pillow renderer protocol, visible-layer compositing, layer-major schedules, deterministic PNG frames, FFmpeg H.264 |
| Integration | Coordinator, GPT-5.6 Sol, high | Parser-to-render projection composing group transforms before the explicit page affine transform |

Acquisition verification fixture: `fixtures/private/verification/8aba68ff-00e9-400b-9772-b96322e000f0/` (ignored). The USB archive and five-page native PDF pass structural checks. Poppler rasterized five 890×1188 PNGs at 144 DPI. It emitted non-fatal unknown `ExtGState GSa` warnings.

Complete SSH snapshot: `fixtures/private/verification/ssh-v3/8aba68ff-00e9-400b-9772-b96322e000f0/` (ignored). Its manifest records firmware `3.27.3.0`, build `5.7.126 (scarthgap)`, machine `reMarkable Chiappa`, five ordered page IDs, three sidecars and five `.rm` files. All local sizes/hashes match, every file records size/mtime stability, and every SSH `.rm` is byte-identical to its USB archive member.

The older ignored `ssh/` snapshot is intentionally retained as incomplete diagnostic evidence; it predates support for current `cPages.pages` metadata and contains only sidecars. `ssh-v2/` is complete but predates device-provenance fields. Neither is a valid canonical snapshot; use `ssh-v3/`.

`rmscene 0.8.0` parsed all five real v6 pages: 10,494 strokes and 312,252 points total, with zero unreadable blocks, unparsed extras or adapter warnings. The sample exposes tool codes 6, 13–17 and 21, and colours 0 and 2. `SceneInfo.paper_size` is absent on all five pages. The library discards a line-internal tag-6 timestamp; the exposed CRDT item ID remains available, and replay order remains explicitly labeled as an unverified deterministic fallback.

The first anchored-group implementation used the community `rmc` text-layout constants. User review correctly found that the layers were still vertically displaced. Five-page comparison against the paired native PDF isolated the problem to anchored content: the unanchored base layer already aligned, while every page's anchored content needed about 145 source units of Y correction. A fixture-calibrated origin of `text.pos_y + 63` and 69.5-unit plain-paragraph spacing reduces whole-page residual Y registration from 145.2–145.9 source units to -0.2–1.0 across all five pages without moving unanchored ink. Mean candidate-centerline distance to native ink falls from 8.04 to 1.23 pixels, and the fraction within three pixels rises from 57.6% to 91.0%. Before/after overlays and per-transform measurements are under the ignored fixture `diagnostics/` directory. Of the 312,208 points included in the per-transform diagnostic, one page-2 transform containing 1,805 of 57,447 page points remains a 260-unit outlier against the flattened native PDF; the remaining 310,403 measured points are within four source units. This calibration is proven only for the paired notebook and its empty plain-paragraph anchors.

The render projection now retains top-level layer visibility. Static rendering and all replay schedules omit hidden layers. Replay scheduling completes visible layers in final bottom-to-top compositing order and preserves the parser's inferred order within each layer; global CRDT order no longer interleaves layers. A direct module smoke check scheduled all 10,494 real-fixture strokes layer-major across the five pages, and page 1's completed replay frame was byte-identical to its static Pillow render. All layers in this fixture are visible, so hidden-layer behavior is verified with synthetic tests. Final compositing order remains unchanged.

Native-exact rendering remains unclaimed. Page geometry and the `+702` horizontal source translation are still supplied explicitly, the native PDF is flattened so individual native layer rasters are unavailable, and the Pillow baseline does not reproduce pressure, textured tools, or eraser semantics.

## Next coordination queue

1. Validate the calibrated anchor origin and style-specific line heights on independent notebooks, especially non-empty text and non-plain paragraph styles; investigate the isolated page-2 transform outlier.
2. Confirm actual page geometry and the global source-to-page transform instead of promoting the fixture-specific 1404×1872 size and `+702` X translation into core defaults.
3. Add a small end-to-end command that snapshots/selects a page, parses it, projects it, emits deterministic frames, and encodes a replay.
4. Run the final-frame equality gate through that real-page command. Treat eraser semantics and textured pens as known baseline limitations.
5. Promote the existing comparison diagnostics into supported tooling on GPT-5.6 Terra, medium: fixed Poppler settings, global and ink-ROI metrics, diffs and overlays.
6. Build controlled fixture tooling only after explicit device-write opt-in. Then assign simple-pen work to Sol high and pencil/brush research to Astra high.

Official runtime references: [CPython version status](https://devguide.python.org/versions/), [Python 3.13.15](https://www.python.org/downloads/release/python-31315/), and [uv Python version management](https://docs.astral.sh/uv/concepts/python-versions/).
