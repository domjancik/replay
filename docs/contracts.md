# Shared contracts v2

This document freezes the integration boundary. Version 2 corrects the parsed page transform from a silently assumed identity to an optional evidence-backed value. Additive evolution is allowed; further renames, type changes, or semantic changes require coordinator review and a version bump.

## Standalone Rust renderer ABI v1

The additive `native/renderer` backend consumes normalized render-page JSON, render options and optional visibility. It does not acquire or parse raw tablet files, resolve text anchors, schedule frames or encode video. It implements the current Python renderer's ink profiles, including their experimental fidelity limitations. A null visibility renders the complete static page. Reveal order never changes layer compositing order; the final forward frame must equal static RGBA for the same options.

The Rust library and standalone WASM share owned input allocation/free and output pointer/length calls. Input is bounded to 32 MiB. All native calls for an instance must occur on the same thread; write input only before the render call and copy result/error bytes before the next call that replaces them. The JavaScript adapter refreshes memory views after potential WASM growth and returns a copied RGBA buffer. The standalone ABI retains completed-stroke prefixes per visible layer and the last rendered visibility state within a 64 MiB persistent RGBA-canvas budget. Page/options changes and errors discard the cache; backward progress rebuilds affected prefixes, while non-prefix or oversized requests use the stateless renderer. Active strokes render onto temporary copies, preserving compositing and eraser semantics. Validation constrains dimensions and numeric geometry; it does not provide a strict CPU-time or peak-memory budget. Hosts accepting untrusted requests must isolate rendering in a cancellable worker/process.

The Python reference and both Rust targets are compared on the same immutable normalized inputs and raw RGBA. This verifies backend compatibility, not equivalence to proprietary reMarkable rendering. Build and reproduction instructions are in `docs/rust-renderer.md`.

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

The render projection retains top-level layers in their final bottom-to-top compositing order and carries each layer's visibility. Replay scheduling defaults to layer-major: omit hidden layers, finish every stroke in the lowest visible layer before starting the next visible layer, and preserve the parser replay order relative to other strokes within the same layer. The optional entry ordering instead retains the global parser replay sequence across visible layers; it does not assert verified chronology. Visual compositing always follows the layer stack.

## Replay and rendering

The renderer consumes a normalized page, immutable render options, and a visibility state:

- parsed tool identity and the retained pressure, speed, direction, and width channels for each point
- completed stroke IDs
- optional active stroke ID
- active progress as a normalized point/distance fraction

For pages containing visible, composited current app-profile pencil or current brush, a viewport smaller than the source paper raster is produced by composing at at least source resolution on each axis, then BOX-reducing the complete frame once. Ordinary ordered source-over, explicit RGBA, erasers and layer order are preserved; shared grain is not blended with a color-based maximum heuristic. This avoids filling paper holes through repeated compositing of individually downsampled strokes. The cache retains source-resolution canvases, so memory depends on source dimensions rather than only the requested preview dimensions. Legacy pencil-only profiles retain their earlier viewport behavior. The manifest records `current_texture_downsampling: compose-at-source-then-box`.

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

Backend provenance labels the default textured-tool model `experimental-texture-v7-clustered-app-png` and records that it is not fully native-calibrated. Current pencil and mechanical pencil share a one-source-unit grain field, a weak four-source-unit field modulating deposition odds, a separate irregular boundary field, and a monotone pressure-occupancy curve capped at 0.97 to retain pinholes. Fourfold area sampling integrates coverage. The current brush uses correlated low-pressure clusters with fine modulation, irregular edges and twofold area sampling; its separate provenance is `experimental-brush-app-png-v2`. These are statistical app-PNG fits, not recovered native textures. Legacy tools remain unchanged. Source-over and explicit RGBA semantics are unchanged. Fixed source-distance deposition is shared by static and progressive rendering; determinism does not imply native fidelity.

Calligraphy provenance records `provisional-calligraphy-raw-width-v1` and `4x-pixel-center-area-coverage`. Tool 21 uses a quarter-unit raw-width envelope, evaluated on the original segments at fixed subpixel centers, then area-averaged and composited with source alpha once per stroke. This provides antialiased, stable progressive edges. Captured single/coincident-point paths are blank. Native wide-stroke contours, variable-width tessellation and a directional nib model remain unproven; pressure, speed, direction and thickness do not independently rescale the measured constant-width controls.

Simple-pen provenance identifies `current-simple-geometry-v1` (current fineliner and highlighter) and `provisional-marker-envelope-v1`. Fineliner holds the first point's quarter-unit width throughout the stroke. Highlighter Darken blending is scoped to the current layer; native equivalence across layers is unverified. Marker contours and variable-width highlighter/marker interpolation remain provisional.

Backend provenance also records the default palette profile and the measured color codes. `native-basic-3.28-v1` uses native export values for black, gray, yellow, blue and red (codes 0, 1, 3, 6, 7); yellow is measured on highlighter exports. Other default colors remain provisional. Explicit source RGBA and caller-supplied palettes override these defaults.

Supported scheduling modes are stroke-step, constant seconds per stroke, and constant drawing distance per second. All use the visible-layer-major ordering defined above. A run is unsuccessful if the final frame differs from `static.png`.

## Comparison

Reference rasterization records PDF hash, rasterizer/version, page, DPI or exact dimensions, colour space, background, crop, and output hash. Candidate and native images must share those settings.

Metrics include global and padded-ink-ROI MAE, RMSE, SSIM, coverage/ink density, and an edge/geometry measurement. Reports retain per-page and, when fixtures isolate tools, per-pen values. No fidelity claim may rely on a mostly white full-page metric alone.

The supported local comparison command consumes an existing candidate PNG plus either a native PNG of identical dimensions or a native PDF page rasterized to the candidate dimensions with Poppler. It never contacts the tablet. Each run writes to a new output directory and records input hashes, Poppler version/settings when used, dimensions, colour/background handling, ROI construction, metric definitions and output hashes. Required outputs are `native.png`, `ours.png`, `absolute-diff.png`, `high-gain-diff.png`, `overlay.png`, and `metrics.json`. Dimension or colour-mode mismatches fail actionably rather than triggering an implicit resize or crop.

For native PDFs, ink-only comparison removes direct page-content text objects before rasterization and records the number of removed text and text-painting operators. The report labels this scope explicitly. Form XObjects, images, annotations, and their clipping or masking interactions remain unfiltered, so this mode supports only PDFs whose relevant typed text is in direct page content.

## Corpus layout

Use `raw/`, `native/`, `rendered/`, and `diff/`. `raw/` and private native exports are ignored by default. Selective synthetic fixtures and approved redistributable goldens may be committed with provenance manifests.

Current pencil codes 13/14 are fitted only to 27 horizontal app-PNG pressure controls spanning nine pressures and three widths. The brush occupancy/edge fit uses five pressure controls. Other control cells and physical tilt worksheets are excluded from fitting. Improved ink mass and overdraw do not establish pixel equivalence: exact grain phase and structure remain unknown, and pencil pixel error can increase despite closer total ink amounts. Stored tilt/direction is not reapplied as an extra pencil width multiplier; recorded width already varies in the physical tilt samples.

Rendering optimizations preserve texture v7 pixel output. Current-pencil pressure-independent grain, boundary and occupancy-gain fields are cached as read-only float64 tiles keyed by absolute supersampled tile coordinates and both exact scale factors. Production uses 16 tiles of 256-by-256 samples: at most 24 MiB of retained field arrays, plus temporary arithmetic/storage. Tiles are shared across pages because this profile's paper fields depend only on source coordinates, not document identity. Eviction affects speed only. Stroke alpha buffers cover conservative clipped stroke bounds; integer global origins preserve sampling phase and output-pixel alignment for BOX filtering. Only reached dabs deposit ink, even when buffer bounds include later points.

The opt-in `RenderOptions.pencil_boundary=True` / replay `--pencil-boundary` retains the older PDF-fitted `experimental-texture-v5-sparse-boundary` pencil profile for comparison. It adds sparse signed boundary offsets capped at 0.75 source units and 30% of radius to the older pressure/interior grain model. It selects that older pencil profile instead of the default app-PNG profile; current brush still uses the separately identified app-PNG model. The option participates in replay cache identity and backend provenance.

Reference labels must identify the export path: app-exported PNG, USB-exported PDF with named rasterizer/settings, or device screenshot. Do not label these interchangeably as "Native" or infer app fidelity from PDF-only metrics. The page-12 app/PDF audit found materially different local tonal distribution despite nearly equal full-resolution global ink density. Preserve the reference resolution and record any display downsampling. PDF renderer diagnostics, including the observed undefined GSa graphics state, require explicit investigation rather than silently treating a successful rasterization as a fully qualified app reference.


The optional `RenderOptions.pencil_backend="rust"` / replay `--pencil-backend rust` replaces only current pencil deposition with a resident native kernel. Python remains the default. A whole reached stroke crosses the C ABI once; host NumPy pressure interpolation and gain values preserve the calibrated arithmetic. Rust max-unions coverage within that stroke, leaving layer order, stroke composition, reveal timing and source-resolution BOX filtering unchanged. The older `pencil_boundary` profile cannot be selected with Rust. Backend selection participates in renderer cache identity. Explicit Rust selection fails if its library is missing or incompatible; replay preflights before creating output and records library path, SHA256 and ABI version. This implementation choice does not change texture profile v7 or imply equivalence to proprietary tablet rendering.


The local loopback UI is an orchestration layer above acquisition and the existing replay CLI. Raw imports are immutable and rendering never requires live device access after import. USB capture serializes bounded GETs to the fixed tablet host, compares two raw member-hash maps and retains failed attempts. Optional paired PDF sits between those reads; manually attached PDFs carry caller-supplied pairing evidence. Browser requests select opaque local notebook/job IDs, never arbitrary filesystem paths or remote URLs.

Cloud pairing and tree caches belong to an encrypted browser IndexedDB vault, unlocked with a user passphrase that never leaves the browser. Device credentials persist only inside AES-GCM ciphertext; session tokens remain in memory. The fixed-operation HTTPS relay sees credentials transiently but does not persist credentials, trees or downloaded blobs. Normal app operation never discovers or invokes a companion cloud CLI. Browser code validates index/member hashes and builds the selected archive before submitting it to the existing local import pipeline; imported notebooks and replay outputs still persist locally. This boundary is not a fully browser-only rendering deployment or a claim of live-account validation.

The utility may use a separately prepared local text-anchor-layout sidecar for a reviewed page. Its binding must match the complete archive and paired PDF SHA256 hashes, page ID, one-based PDF page, canvas and source affine. It then uses the existing explicit layout CLI path; otherwise automatic PDF fitting remains the default. A present but stale or invalid sidecar is rejected. Imported archive members cannot supply this sidecar. This is page-specific placement evidence, not a general automatic-layout claim.

The additive replay mode `duration` / `--duration SECONDS` samples an equal-time-per-visible-stroke timeline at a fixed total drawing duration. Multiple strokes may complete per output frame; partial strokes retain directional progress. Integer quotient/remainder selection preserves exact stroke boundaries, layer-major order and a fully completed final frame. Initial and final holds are additive; per-stroke pauses are rejected for this mode. Other modes keep their existing semantics. The manifest records `duration_seconds`.

Replay scheduling accepts `ordering="layer"` (default) or `ordering="entry"` in every timing mode. CLI `--ordering` and the local UI carry the choice into the replay manifest as `replay.ordering`. Entry ordering filters hidden layers without regrouping the remaining parser replay entries. Parser `replay_strategy` still determines the underlying inferred sequence; the default remains CRDT order. Rendering/compositing and final/static equality are independent of this choice.

Crop/loop exports derive from completed original replay frames, without rerendering ink. Crops use one fixed even-pixel rectangle for every frame and static output. The final **forward** frame must remain byte-identical to the cropped static PNG. Optional 2x/4x/8x reverse skips the repeated final hold and ends on the first frame for a matching loop seam; the final frame of the whole loop therefore need not equal static output. Derived manifests distinguish these checks and record source manifest hash, requested/effective crop, reverse speed and source frame indices. H.264 is lossy; equality checks apply to lossless source frames.

The local UI rejects submissions whose resolved visible stroke centers fall outside the selected canvas unless `allow_clipping` is explicitly true. It does not infer native export extents, measure all stroke-edge coverage, or validate unresolved text anchors. Scrolling SceneInfo may record base screen dimensions; callers retain responsibility for evidenced full-page geometry. CLI H.264 output requires even viewport dimensions and rejects odd dimensions before creating frames. Ink-only PDF comparison records the original source `pdf_page` separately from the single-page intermediate `filtered_pdf_page`.


The Python/Pillow orchestration path (including its Rust pencil backend) retains per-layer completed-stroke prefixes for interleaved entry-order replay within a 64 MiB persistent RGBA-canvas budget. This budget excludes temporary compositing images and texture caches. Unsupported or oversized cases retain the stateless path; page identity and options invalidate retained pixels. Identical consecutive visibility states reuse PNG bytes by file copy, preserving independent frame files and the existing compression settings. Static verification remains independent. The standalone full-page Rust/WASM ABI now uses the equivalent bounded per-layer prefix and repeated-frame strategy; it still parses the complete JSON page on each call.

## Optional USB desktop bridge

The companion is independent of cloud pairing, rendering and file import. It binds only loopback port 8786, requires an exact configured origin and an ephemeral connection key on every GET, and exposes only status, folder listing and stable raw notebook download. It reuses the fixed-host read-only USB reader. The browser adapter returns bounded archive bytes to the existing import consumer; it must not forward them to a hosted service implicitly. No cloud tokens or raw notebook files are persisted by the companion. Preflight allows the one origin, GET and the key header only. See `docs/usb-companion.md` for the desktop lifecycle and validation limits.

## Legacy v5 notebook pages

The parser dispatches the 43-byte version-5 header to a bounded layer/stroke adapter instead of the v6 CRDT reader. The [documented binary layout](https://github.com/akeil/rmtool#rm-lines-format) supplies layers, strokes and six float point channels. Original float channels, unknown stroke words and trailing bytes are preserved in diagnostics. IDs are synthetic and replay order is explicitly stored layer/stroke order, not recovered chronology. Missing layer visibility defaults to visible and is labeled; paper dimensions still require external/caller evidence.

V5 source coordinates are top-left based, so their parsed source transform is identity. Browser selection and lazy preview requests use the returned source translation instead of adding the v6 centered-X offset. The renderer projection converts the legacy float channels into the units already used by the renderer: pressure x255, speed x4, width x4 and direction x255/(2*pi), matching rmscene's float-point conversion convention. Raw diagnostic points remain unchanged. This enables legacy files; it does not establish new native-fidelity calibration for v5 tools.

## Hosted native replay core

`native/replay-core` exposes an independent version-1 owned-buffer JSON ABI for anchor matching and duration scheduling. It takes normalized data, never imports a parser or renderer, and rejects oversized requests. Browser PDF.js supplies text-filtered native vector ink masks; Rust supplies distance transforms, search and confidence checks. Accepted shared-anchor offsets must agree and retain the attached PDF SHA-256 and rasterization evidence in the job manifest. Unsupported or ambiguous layouts fail explicitly rather than using an unverified offset.

The browser stores attached reference PDFs locally. Native-reference matching does not reconstruct typography from raw data or establish fidelity for unsupported shapes. Rust schedule output preserves entry/layer choice independently of compositing order; the renderer still checks final-forward/static byte equality. Parsing and normalization now run in the independent `native/rmdoc` Rust/WASM crate. The Python path remains the development oracle.

## Native notebook reader

`rm-rmdoc` decodes bounded `.rmdoc` archives and explicitly dispatched v5/v6 page formats, with no renderer or acquisition dependency. Its version-1 owned-buffer WASM ABI accepts raw bytes separately from JSON options; it has no host imports. Normalized geometry, channels, groups, IDs, metadata and order retain the existing parsed-page contract. Diagnostic framing is implementation-specific and preserves unknown payloads, extensions and numeric enum values. Caller-supplied text layout remains evidence-bearing.

Unknown file major versions fail. Unreadable potentially geometric or unknown block types remain available to diagnostic consumers but reject render projection; informational types 0, 9 and 10 may remain diagnostic-only. This is intentionally stricter than permissive Python projection. ZIP64 directories and multidisk archives reject. API/schema changes and new format support follow `native/rmdoc/FORMAT_UPDATES.md`; compatibility is established by synthetic and opt-in private differential fixtures, not by accepting an upstream version number.
