# rm-redraw

Local, read-only tooling for acquiring native reMarkable documents, parsing complete stroke metadata, replaying strokes, and developing a renderer against tablet-native PDF exports.

The source brief is [Codex Brief — reMarkable Stroke Replay + High-Fidelity Renderer.md](./Codex%20Brief%20%E2%80%94%20reMarkable%20Stroke%20Replay%20%2B%20High-Fidelity%20Renderer.md). Current kickoff evidence is in [plans/kickoff-readiness.md](plans/kickoff-readiness.md), and shared interfaces are frozen in [docs/contracts.md](docs/contracts.md).

## Development environment

CPython does not publish a separately branded LTS channel. This project pins CPython 3.13.15, the current 3.13 maintenance release as of 2026-09-05. Python 3.13 is presently in its bugfix phase; it later receives security-only fixes before reaching end of life in October 2029. The pinned parser supports Python 3.13.

`rmscene==0.8.0` is the parser baseline. `rmc==0.3.0` is intentionally excluded from the main environment because it requires `rmscene<0.7`; it remains a renderer reference and can be evaluated in an isolated environment.

```powershell
uv sync --all-groups
uv run pytest
uv run ruff check .
```

Device-derived files belong under `fixtures/private/` or `fixtures/local/` and are excluded from Git. Existing tablet content is always read-only. Device writes require a separate explicit opt-in and may target only dedicated fixture documents.

## Local replay command

For smooth directional drawing, select `--mode distance-per-second --distance-per-second 420` or `--mode seconds-per-stroke --seconds-per-stroke 0.5`. The default `stroke-step` mode reveals whole strokes. Use `--initial-pause 0.4 --pause-between-strokes 0.25 --final-hold 0.8` with either progressive mode to control pacing. These durations are synthesized; neither timing nor CRDT order is claimed to reproduce recorded wall-clock chronology. Visible layers finish from lowest to highest.

The renderer includes a provisionally calibrated ballpoint profile and layer-local erasing. Experimental pencil, mechanical-pencil and brush profiles use deterministic source-position grain and fixed deposition samples, so revealing a prefix does not resample its texture. These profiles are not yet native-calibrated, and speed response is not established. See [the milestone acceptance audit](plans/milestone-acceptance.md) for verified behavior and remaining fidelity gaps.

Replay one local `.rm` page or a selected page from a local `.rmdoc` archive:

```powershell
uv run python -m rm_redraw.replay path/to/page.rm `
  --output artifacts/replay-example `
  --paper-size 1404 1872 `
  --source-affine 1 0 0 1 702 0 `
  --viewport 280 376 `
  --mode seconds-per-stroke `
  --seconds-per-stroke 0.5 `
  --fps 30
```

The geometry values above are explicit example inputs, not device defaults. Omit `--paper-size` only when the page contains `SceneInfo.paper_size`; supply a source affine transform unless parsed metadata provides one. Multi-page `.rmdoc` archives also require `--page-id`.

Root-text anchor matrices derived from the fixture-calibrated typography heuristic are retained for diagnostics but marked unresolved. Controlled native exports establish that type-2 group Y is `RootText.pos_y + final_layout_anchor_offset`; the stored threshold is not applied as a static cap or deadband. The raw scene does not contain native shaped line boxes, visual baselines, font metrics, or a stored anchor Y. A real edited document also places a later logical anchor above an earlier one, so a monotonic layout of the final CRDT text cannot reproduce both positions. Native-equivalent offsets therefore require external evidence or additional editing-history data; the parser does not label a current-text estimate as resolved.

Callers that already have evidence-backed offsets can supply them without coupling parsing to a renderer. The values are source-space Y offsets from `RootText.pos_y`, keyed by CRDT anchor ID:

```json
{
  "schema_version": 1,
  "evidence": "native-equivalent final text layout",
  "offsets": {
    "1:2206": 2258.6
  }
}
```

Pass the file as `--text-anchor-layout path/to/anchor-layout.json`. Matching anchors are marked resolved and the file path, evidence, and offsets are recorded in `manifest.json`; missing IDs continue to use the unresolved diagnostic heuristic.

When a matching native PDF is available, add `--auto-text-anchors` alongside `--paired-native-pdf` and `--export-canvas` to derive offsets automatically. The command uses the local native raster, rejects ambiguous or unsupported matches before creating output, and records per-group decisions and source hashes. It cannot be combined with `--text-anchor-layout`. This is native-reference-assisted placement, not a raw-only typography engine; no tablet connection is required after the paired files are saved.

When a paired native export establishes the target canvas, provide the local PDF and caller-validated canvas together. The command hashes and validates the PDF/page, records its MediaBox, and derives the centered X transform from the supplied width without assuming a DPI:

```powershell
uv run python -m rm_redraw.replay path/to/document.rmdoc `
  --page-id PAGE_UUID `
  --paired-native-pdf path/to/native.pdf `
  --paired-pdf-page 1 `
  --export-canvas 1872 6136 `
  --output artifacts/replay-paired
```

Each successful run creates deterministic numbered PNG frames, `static.png`, H.264 `replay.mp4`, and `manifest.json`. The manifest records input and output hashes, geometry and optional text-anchor evidence, timing, viewport, backend, and the final-frame equality result. The command fails if its final frame is not byte-identical to the static render.

## Local comparison command

Compare a candidate PNG with either a same-size native PNG or one page of a native PDF:

```powershell
uv run python -m rm_redraw.comparison artifacts/replay-example/static.png `
  --native-pdf fixtures/private/example/native.pdf `
  --page 1 `
  --output artifacts/comparison-example
```

Use `--native-png` instead of `--native-pdf` for a pre-rasterized reference. PNG inputs must have identical dimensions and must both use RGB or both use RGBA; convert them explicitly before comparison when their modes differ. Each run requires a new output directory and writes normalized input copies, absolute and high-gain differences, a red/native–blue/candidate overlay, and a provenance-rich `metrics.json` report with global, ink-ROI, and edge-geometry measurements.

Add `--ink-only` with `--native-pdf` to remove direct page-content text objects before rasterization. The report records the filtered operators and explicitly lists unfiltered Form XObjects, images, and annotations.

## Ballpoint rendering

The render projection preserves the parsed tool code/name and all point channels. `BALLPOINT_2` uses five-point segments with recorded width, pressure, and speed, rounded caps/joins, pressure-dependent colour, and localized two-times antialiasing. Other tools retain the fixed-width Pillow baseline until they receive isolated validation.

The controlled three-stroke ballpoint page improved from ROI RMSE `29.9361` to `18.3519`, SSIM `0.941389` to `0.973088`, and symmetric edge distance `0.50431` to `0.38154` pixels. Candidate/native ROI coverage is `0.05072`/`0.04622`. This is one geometry-isolated fixture; the `0.75` Pillow width calibration remains provisional until held-out ballpoint pages cover more pressure, speed, and thickness ranges.
