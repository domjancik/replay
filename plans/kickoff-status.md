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
| Parser | GPT-5.6 Sol, high | v6 `rmscene` adapter, lossless normalized metadata exposed by the library, diagnostics and CLI |
| Baseline replay | GPT-5.6 Terra, high | Pillow renderer protocol, layer compositing, schedules, deterministic PNG frames, FFmpeg H.264 |
| Integration | Coordinator, GPT-5.6 Sol, high | Parser-to-render projection with explicit page size and affine source transform |

Acquisition verification fixture: `fixtures/private/verification/8aba68ff-00e9-400b-9772-b96322e000f0/` (ignored). The USB archive and five-page native PDF pass structural checks. Poppler rasterized five 890×1188 PNGs at 144 DPI. It emitted non-fatal unknown `ExtGState GSa` warnings.

Complete SSH snapshot: `fixtures/private/verification/ssh-v3/8aba68ff-00e9-400b-9772-b96322e000f0/` (ignored). Its manifest records firmware `3.27.3.0`, build `5.7.126 (scarthgap)`, machine `reMarkable Chiappa`, five ordered page IDs, three sidecars and five `.rm` files. All local sizes/hashes match, every file records size/mtime stability, and every SSH `.rm` is byte-identical to its USB archive member.

The older ignored `ssh/` snapshot is intentionally retained as incomplete diagnostic evidence; it predates support for current `cPages.pages` metadata and contains only sidecars. `ssh-v2/` is complete but predates device-provenance fields. Neither is a valid canonical snapshot; use `ssh-v3/`.

`rmscene 0.8.0` parsed all five real v6 pages: 10,494 strokes and 312,252 points total, with zero unreadable blocks, unparsed extras or adapter warnings. The sample exposes tool codes 6, 13–17 and 21, and colours 0 and 2. `SceneInfo.paper_size` is absent on all five pages. The library discards a line-internal tag-6 timestamp; the exposed CRDT item ID remains available, and replay order remains explicitly labeled as an unverified deterministic fallback.

The end-to-end parser-to-Pillow smoke retained all 845 strokes on the selected page with no unmapped layers and produced `artifacts/smoke/real-page-x-centered.png` (ignored). It is not native-aligned: an explicit horizontal-origin translation improves placement, but group/move transforms are not yet reconstructed, leaving duplicated/shifted historical content. This is the main integration gap before presenting the first real replay video.

## Next coordination queue

1. Reconstruct effective scene/group movement and page transforms, backed by the real paired fixture. Confirm actual page geometry instead of promoting the fixture-specific 1404×1872 inference into a core default.
2. Add a small end-to-end command that snapshots/selects a page, parses it, projects it, emits deterministic frames, and encodes a replay.
3. Run the final-frame equality gate through that real-page command. Treat eraser semantics and textured pens as known baseline limitations.
4. Start comparison tooling on GPT-5.6 Terra, medium after the first real replay: fixed Poppler settings, global and ink-ROI metrics, diffs and overlays.
5. Build controlled fixture tooling only after explicit device-write opt-in. Then assign simple-pen work to Sol high and pencil/brush research to Astra high.

Official runtime references: [CPython version status](https://devguide.python.org/versions/), [Python 3.13.15](https://www.python.org/downloads/release/python-31315/), and [uv Python version management](https://docs.astral.sh/uv/concepts/python-versions/).
