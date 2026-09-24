# Shared contracts v2

This document freezes the integration boundary. Version 2 corrects the parsed page transform from a silently assumed identity to an optional evidence-backed value. Additive evolution is allowed; further renames, type changes, or semantic changes require coordinator review and a version bump.

## Snapshot manifest

A snapshot directory is immutable after successful acquisition. Its `manifest.json` contains:

- `schema_version`: exactly `1`
- `source`: provider (`ssh` or `usb-api`), device address, machine, firmware/build, and acquisition timestamp in UTC
- `document`: UUID, visible name, parent UUID, document type, and ordered page UUIDs
- `files`: relative POSIX path, byte size, SHA-256, source mtime where available, and stability evidence for every copied file
- optional `paired_exports`: raw archive and native PDF provenance and hashes

Paths are relative to the snapshot root. Acquisition rejects traversal and absolute paths. `raw/` is never mutated after the manifest is finalized.

## Normalized page

A normalized page retains source information rather than flattening it to render-only paths:

- stable page ID, optional `paper_size`, page metadata, and optional evidence-backed source-to-page transform; absence remains `null` rather than silently meaning identity
- ordered groups/layers with stable IDs, scene relationships, and visibility
- strokes with stable/CRDT ID, parent, layer, scene ordering data, move ID, tombstone/deletion relationships, pen/tool, palette colour, explicit RGBA, thickness scale, starting length, and ordered points
- each point retains `x`, `y`, `pressure`, `speed`, `direction`, `width`, plus unknown channels/fields in `extra`
- raw point coordinates remain unchanged; groups and strokes expose resolved local/cumulative transforms with evidence and anchor IDs. Rendering composes the page transform after the stroke's cumulative group transform.
- A best-effort anchor matrix may be retained for diagnostics while `resolved` remains false. Fixture-calibrated typography constants or paragraph-count heuristics do not establish full text-layout semantics and must not be labeled resolved.
- For type-2 root-text anchors, controlled native evidence establishes `group_y = RootText.pos_y + final_layout_anchor_offset(anchor_id)`. The parser may accept caller-supplied, evidence-bearing source-space offsets and mark only matching IDs resolved. It does not apply `anchor_threshold` as a static cap, deadband, or excess subtraction. Missing offsets remain heuristic and unresolved.
- unreadable or unknown blocks remain represented in diagnostics with their type and raw bytes encoded safely

Parser `compositing_order` and `replay_order` are separate stroke sequences. Replay order includes `strategy` (`verified-chronology`, `crdt-order`, or `scene-order`) and an evidence note. Only controlled device evidence permits `verified-chronology`.

The render projection retains top-level layers in their final bottom-to-top compositing order and carries each layer's visibility. Replay scheduling is layer-major: omit hidden layers, finish every stroke in the lowest visible layer before starting the next visible layer, and preserve the parser replay order relative to other strokes within the same layer. A global chronology must not interleave layers.

## Replay and rendering

The renderer consumes a normalized page, immutable render options, and a visibility state:

- parsed tool identity and the retained pressure, speed, direction, and width channels for each point
- completed stroke IDs
- optional active stroke ID
- active progress as a normalized point/distance fraction

Static rendering is the same call with all drawable items visible. The viewport is resolved once from page metadata/options and stays fixed for every frame. Layer/group compositing is recomputed correctly for visible state; a newly revealed lower-layer stroke cannot cover an already-visible upper-layer stroke.

Timing synthesis is separate from geometry and supports constant time per stroke and constant drawing distance per second. Texture seeds derive only from stable input fields such as stroke ID, segment index, position, and pen parameters.

For identical normalized input, visibility state, options, dependency lock, and backend version, image bytes must be deterministic. The final replay frame must equal static rendering byte-for-byte. Encoded video container bytes are not initially required to be byte-identical; decoded frames are.

## Page geometry

Page geometry is a resolved value containing `paper_size`, the six-value affine `source_to_page_transform`, and human-readable evidence for both. Resolution may use explicit source `SceneInfo`, immutable document/page metadata, or caller-supplied values. It must never silently substitute a model-specific viewport or the `+702` translation measured from the first paired fixture. When source metadata is insufficient, callers must supply the missing values explicitly and the result must identify them as caller-supplied.

Paired native PDF dimensions are comparison/render-target evidence, not by themselves proof of the source coordinate transform. Geometry inferred from a device model or a paired export remains labeled as inferred until an independent source or multiple fixtures validate it.

When paired evidence supports a centered source frame, `width / 2` may be supplied from the actual validated target/export width. It is not an unconditional default when source page size is absent or conflicts with legacy viewport metadata.

## Local replay command

The end-to-end replay command consumes an existing local `.rmdoc` archive or `.rm` page. It never contacts the tablet implicitly. Multi-page archives require an explicit page ID. The command accepts explicit page size and source affine transform overrides, and fails with an actionable message when neither source metadata nor overrides resolve the geometry.

The command may also accept a schema-versioned JSON text-anchor layout containing nonblank evidence and finite source-space offsets keyed by `PART1:PART2` CRDT ID. It records the file path, evidence, and normalized offsets in the output manifest. Supplying measured offsets resolves placement for that input; it does not claim or substitute a general text-layout engine.

Explicit `--auto-text-anchors` derives matching offsets from the paired local native PDF and validated export canvas. It conflicts with manual layout input. The comparison module rasterizes the supported ink-only PDF scope through Poppler and rejects ambiguous, weak or unsupported matches. Replay reparses the unchanged raw page using accepted evidence; rejection fails before output creation. A page without applicable anchors is a documented no-op. The manifest records automatic origin, group decisions, PDF/page hashes, canvas and affine provenance. This remains native-reference-assisted placement, not raw-only text layout.

Callers may instead provide a local paired native PDF, one-based PDF page, and a caller-validated export canvas. The command hashes the PDF, validates the page and MediaBox, records that provenance, uses the export canvas only when `SceneInfo.paper_size` is absent, and derives a centered `(1, 0, 0, 1, width / 2, 0)` transform only when no explicit or parsed affine exists. A conflicting `SceneInfo.paper_size` requires an explicit paper-size override. The export canvas remains caller-supplied evidence; PDF points alone do not imply a DPI or source scale.

Each successful run writes into a new output directory:

- deterministic numbered PNG frames under `frames/`
- `static.png` from the same renderer and options
- `replay.mp4` encoded as H.264
- `manifest.json` containing the input hash and page member/ID, resolved geometry and evidence, replay mode/timing inputs, viewport, frame count and hashes, renderer/backend identity, and a boolean final-frame byte-equality result

Backend provenance labels the current textured-tool model `experimental-texture-v1` and records that it is not native-calibrated. Deterministic output does not imply native fidelity. Its fixed source-distance deposition and stroke/position seed are shared by static and progressive rendering.

Supported scheduling modes are stroke-step, constant seconds per stroke, and constant drawing distance per second. All use the visible-layer-major ordering defined above. A run is unsuccessful if the final frame differs from `static.png`.

## Comparison

Reference rasterization records PDF hash, rasterizer/version, page, DPI or exact dimensions, colour space, background, crop, and output hash. Candidate and native images must share those settings.

Metrics include global and padded-ink-ROI MAE, RMSE, SSIM, coverage/ink density, and an edge/geometry measurement. Reports retain per-page and, when fixtures isolate tools, per-pen values. No fidelity claim may rely on a mostly white full-page metric alone.

The supported local comparison command consumes an existing candidate PNG plus either a native PNG of identical dimensions or a native PDF page rasterized to the candidate dimensions with Poppler. It never contacts the tablet. Each run writes to a new output directory and records input hashes, Poppler version/settings when used, dimensions, colour/background handling, ROI construction, metric definitions and output hashes. Required outputs are `native.png`, `ours.png`, `absolute-diff.png`, `high-gain-diff.png`, `overlay.png`, and `metrics.json`. Dimension or colour-mode mismatches fail actionably rather than triggering an implicit resize or crop.

For native PDFs, ink-only comparison removes direct page-content text objects before rasterization and records the number of removed text and text-painting operators. The report labels this scope explicitly. Form XObjects, images, annotations, and their clipping or masking interactions remain unfiltered, so this mode supports only PDFs whose relevant typed text is in direct page content.

## Corpus layout

Use `raw/`, `native/`, `rendered/`, and `diff/`. `raw/` and private native exports are ignored by default. Selective synthetic fixtures and approved redistributable goldens may be committed with provenance manifests.
