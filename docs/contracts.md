# Shared contracts v1

This document freezes the first integration boundary. Additive evolution is allowed; renames, type changes, or semantic changes require coordinator review and a version bump.

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

- stable page ID, optional `paper_size`, page metadata, and explicit source-to-page transform
- ordered groups/layers with stable IDs, scene relationships, and visibility
- strokes with stable/CRDT ID, parent, layer, scene ordering data, move ID, tombstone/deletion relationships, pen/tool, palette colour, explicit RGBA, thickness scale, starting length, and ordered points
- each point retains `x`, `y`, `pressure`, `speed`, `direction`, `width`, plus unknown channels/fields in `extra`
- raw point coordinates remain unchanged; groups and strokes expose resolved local/cumulative transforms with evidence and anchor IDs. Rendering composes the page transform after the stroke's cumulative group transform.
- unreadable or unknown blocks remain represented in diagnostics with their type and raw bytes encoded safely

Parser `compositing_order` and `replay_order` are separate stroke sequences. Replay order includes `strategy` (`verified-chronology`, `crdt-order`, or `scene-order`) and an evidence note. Only controlled device evidence permits `verified-chronology`.

The render projection retains top-level layers in their final bottom-to-top compositing order and carries each layer's visibility. Replay scheduling is layer-major: omit hidden layers, finish every stroke in the lowest visible layer before starting the next visible layer, and preserve the parser replay order relative to other strokes within the same layer. A global chronology must not interleave layers.

## Replay and rendering

The renderer consumes a normalized page, immutable render options, and a visibility state:

- completed stroke IDs
- optional active stroke ID
- active progress as a normalized point/distance fraction

Static rendering is the same call with all drawable items visible. The viewport is resolved once from page metadata/options and stays fixed for every frame. Layer/group compositing is recomputed correctly for visible state; a newly revealed lower-layer stroke cannot cover an already-visible upper-layer stroke.

Timing synthesis is separate from geometry and supports constant time per stroke and constant drawing distance per second. Texture seeds derive only from stable input fields such as stroke ID, segment index, position, and pen parameters.

For identical normalized input, visibility state, options, dependency lock, and backend version, image bytes must be deterministic. The final replay frame must equal static rendering byte-for-byte. Encoded video container bytes are not initially required to be byte-identical; decoded frames are.

## Page geometry

Page geometry is a resolved value containing `paper_size`, the six-value affine `source_to_page_transform`, and human-readable evidence for both. Resolution may use explicit source `SceneInfo`, immutable document/page metadata, or caller-supplied values. It must never silently substitute a model-specific viewport or the `+702` translation measured from the first paired fixture. When source metadata is insufficient, callers must supply the missing values explicitly and the result must identify them as caller-supplied.

Paired native PDF dimensions are comparison/render-target evidence, not by themselves proof of the source coordinate transform. Geometry inferred from a device model or a paired export remains labeled as inferred until an independent source or multiple fixtures validate it.

## Local replay command

The end-to-end replay command consumes an existing local `.rmdoc` archive or `.rm` page. It never contacts the tablet implicitly. Multi-page archives require an explicit page ID. The command accepts explicit page size and source affine transform overrides, and fails with an actionable message when neither source metadata nor overrides resolve the geometry.

Each successful run writes into a new output directory:

- deterministic numbered PNG frames under `frames/`
- `static.png` from the same renderer and options
- `replay.mp4` encoded as H.264
- `manifest.json` containing the input hash and page member/ID, resolved geometry and evidence, replay mode/timing inputs, viewport, frame count and hashes, renderer/backend identity, and a boolean final-frame byte-equality result

Supported scheduling modes are stroke-step, constant seconds per stroke, and constant drawing distance per second. All use the visible-layer-major ordering defined above. A run is unsuccessful if the final frame differs from `static.png`.

## Comparison

Reference rasterization records PDF hash, rasterizer/version, page, DPI or exact dimensions, colour space, background, crop, and output hash. Candidate and native images must share those settings.

Metrics include global and padded-ink-ROI MAE, RMSE, SSIM, coverage/ink density, and an edge/geometry measurement. Reports retain per-page and, when fixtures isolate tools, per-pen values. No fidelity claim may rely on a mostly white full-page metric alone.

## Corpus layout

Use `raw/`, `native/`, `rendered/`, and `diff/`. `raw/` and private native exports are ignored by default. Selective synthetic fixtures and approved redistributable goldens may be committed with provenance manifests.
