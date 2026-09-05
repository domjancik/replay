# reMarkable stroke replay and high-fidelity renderer

Build a local toolchain for extracting native reMarkable drawings, replaying their strokes as video, and ultimately rendering `.rm` pages with output as close as practical to reMarkable's own renderer.

There are two related workstreams:

**A. Acquisition + parsing + stroke replay**

**B. A near-pixel-perfect reMarkable pen renderer**

Treat A as the infrastructure and initial deliverable. B should build on the same parser, fixture corpus, viewport model, and rendering interface.

The development machine has access to a connected reMarkable device over SSH. The device's local USB web API can also be used. There is an existing **`Drawings`** folder on the tablet that may be used as a source of real-world samples during development.

Default to read-only interaction with existing documents.

---

# Reference projects

Inspect these before implementing major pieces:

- `Scratchydisk/remarkable-rm`
  - TypeScript v5/v6 `.rm` parser.
  - Existing SVG/PNG rendering.
  - Documents the local USB web API.
  - Useful baseline, but current textured-pen fidelity, especially pencil, is insufficient for our target.

- `ricklupton/rmscene`
  - Mature Python v6 parser and scene/CRDT implementation.
  - Particularly useful as a format correctness/reference implementation.

- `ricklupton/rmc`
  - Rendering/conversion layer on top of `rmscene`.

- `RedTTGMoss/librm_lines`
  - C++ parser + real-time renderer.
  - Inspect its pen/stroker implementation and its use of Quill.
  - Treat it as an implementation/reference candidate, especially for textured pens.
  - Check current licensing before copying code rather than merely studying behavior.

- `RedTTGMoss/pylibrm_lines`
  - Python wrapper around `librm_lines`.

- `SamMorrowDrums/remarkable-mcp`
  - Inspect its SSH acquisition and current native notebook/ink authoring implementation.
  - Potentially useful for creating controlled fixture notebooks on-device.

- `CrimsonAS/quill`
  - Variable-width path stroking implementation used/referenced by parts of the reMarkable ecosystem.

Do not rewrite v6 parsing from scratch unless testing demonstrates an actual parser deficiency. Extend an existing parser or implement narrowly scoped missing fields.

---

# Architecture

Keep these concepts separate:

```text
Device acquisition
       ↓
Raw document snapshot
       ↓
.rm parser / scene reconstruction
       ↓
Normalized page + stroke model
       ↓
     ┌──────────────┬────────────────┐
     ↓              ↓                ↓
Static renderer   Replay engine   Diagnostic exporter
     ↓              ↓
 PNG/frame       video frames
```

The parser must not be coupled to the renderer.

The replay engine must not depend on a specific rendering backend.

The renderer should accept a normalized page plus a visibility/progress state so that the same renderer can serve both static pages and animation frames.

---

# PART A — device acquisition, parsing and stroke replay

## Phase A1 — SSH acquisition

First implement acquisition directly from the connected tablet over SSH.

The native store is expected under:

```text
/home/root/.local/share/remarkable/xochitl/
```

Do not assume filenames correspond to visible notebook names. Reconstruct the logical hierarchy from the UUID-based `.metadata` / `.content` files.

Implement:

```text
DeviceSource
  listDocuments()
  findFolder(name)
  getDocument(id)
  snapshotDocument(id)
```

Initial implementation:

```text
SshDeviceSource
```

Requirements:

1. Find the logical folder named `Drawings`.
2. Recursively enumerate notebooks/documents within it.
3. Resolve:
   - visible name
   - document UUID
   - parent UUID
   - page UUIDs
   - `.metadata`
   - `.content`
   - `.pagedata` where present
   - page `.rm` files
   - per-page metadata where present
4. Copy selected documents into a local immutable snapshot directory.
5. Record a machine-readable manifest containing:
   - source device
   - firmware/build if discoverable
   - acquisition timestamp
   - document UUID
   - page UUIDs
   - source filenames
   - hashes of every copied file

Do not modify the source files on the tablet.

Do not stop/restart `xochitl` merely to take snapshots.

Avoid racing a page actively being written. At minimum, verify file size/mtime stability before copying, or copy and hash twice when necessary.

Connection configuration must not contain committed passwords. Support normal SSH config/agent/key usage and optional environment configuration.

---

## Phase A2 — local reMarkable USB API acquisition

Add a second `DeviceSource` implementation for the reMarkable local USB web API.

Expected default host:

```text
http://10.11.99.1
```

Relevant API operations currently include:

```text
GET /documents/
GET /documents/{folder-id}

GET /download/{document-id}/rmdoc
GET /download/{document-id}/placeholder
```

Use the API to obtain two artifacts for the same notebook:

```text
raw/
  document.rmdoc

reference/
  document.native.pdf
```

The `.rmdoc` archive provides the native `.rm` files.

The PDF is produced by the tablet and should be treated as the principal rendering ground truth.

Expose the two acquisition implementations behind the same abstraction:

```text
--source ssh
--source usb-api
```

Eventually it should be possible to acquire a document using both and verify that the raw page contents agree.

Do not introduce the reMarkable cloud API at this stage. "API" here means the connected tablet's local USB web API.

---

# Raw corpus layout

Create a durable local corpus rather than repeatedly operating against the tablet.

For example:

```text
fixtures/
  <document-name>/
    manifest.json

    raw/
      *.metadata
      *.content
      *.pagedata
      pages/
        *.rm

    native/
      document.pdf
      page-001.png
      page-002.png

    rendered/
      page-001.png

    diff/
      page-001-diff.png
      page-001-overlay.png
      metrics.json
```

Never modify files under `raw/`.

Any parser experiments should operate on copies.

---

# Parser and normalized stroke model

Use `remarkable-rm`, `rmscene`, or both as references.

The normalized model must retain substantially more information than is required for a static SVG renderer.

Do not discard metadata merely because the first renderer does not use it.

For each stroke preserve where available:

```text
stable item / CRDT identifier
parent group
layer
scene ordering information
timestamp-like CRDT identifier
moveId
deletion/tombstone relationships
pen/tool type
palette colour
explicit RGBA override
thickness scale
starting length
points[]
```

Each point should retain every raw channel present in the file, including:

```text
x
y
pressure
speed
direction
width
```

Also preserve unknown/new fields in a debug representation where practical.

A major goal is to make future pen reverse-engineering possible without repeatedly changing the parser.

Provide a diagnostic command capable of dumping a page into readable JSON.

---

# Stroke ordering

Do not casually equate scene order, z-order and chronological drawing order.

Maintain distinct concepts:

```text
compositing order
replay order
```

Investigate CRDT item IDs, timestamps/order IDs, insertion relationships, move IDs and tombstones using controlled samples.

Document what can actually be inferred.

If exact chronology cannot be recovered, explicitly support a deterministic fallback such as:

```text
scene-order
crdt-order
```

Do not label something "chronological" until device experiments demonstrate that it is.

---

# Replay engine

The first useful output is a video in which a drawing is reconstructed stroke by stroke.

Support two replay modes:

### 1. Stroke-step replay

Each completed pen stroke appears as one event.

Useful for debugging ordering.

### 2. Progressive stroke replay

Animate through the points within each stroke so that the line visibly grows.

There are no known trustworthy wall-clock timestamps for every point, so timing should be configurable.

Initially support:

```text
constant time per stroke
constant drawing distance per second
```

Then investigate whether the stored `speed` field can be calibrated into a convincing device-like timing model.

Keep timing synthesis separate from geometry.

---

# Replay compositing

Do not simply paint each newly revealed stroke over the existing bitmap.

That breaks layer semantics when a newly revealed stroke belongs underneath content already drawn in another layer.

Instead maintain correct layer/group compositing.

Conceptually:

```text
for each frame:
    determine visible fraction of every stroke
    render each layer in proper layer order
    composite layers
```

Optimisation can later cache completed layers/regions.

Correctness first.

For translucent and textured pens, avoid repeatedly re-rendering an incomplete prefix onto the same persistent surface in a way that makes it progressively darker.

---

# Video output

Produce deterministic image sequences first.

Then support encoding through `ffmpeg` into at least:

```text
MP4 / H.264
WebM optionally
```

Useful controls:

```text
fps
duration or drawing speed
pause between strokes
initial pause
final hold
background
output dimensions
crop: page | content
```

Default to a fixed page viewport.

The frame must never pan/zoom simply because early frames contain fewer strokes.

The final replay frame must be identical to the static rendering produced by the same renderer/configuration.

---

# PART B — high-fidelity reMarkable renderer

The current open-source renderers are acceptable structurally but visibly behind the tablet renderer for several pens, especially textured tools such as pencil and brush.

The target here is:

> Match the reMarkable native export closely enough that side-by-side inspection does not reveal obvious differences, with pixel-level or perceptual tests backing that claim.

Do not optimise for one existing drawing.

Build a systematic renderer model.

---

# Ground truth

Use the tablet's own local API PDF export as the canonical reference for renderer development.

For each test document capture:

```text
raw .rm / .rmdoc
native tablet-rendered PDF
```

Rasterise the native PDF using a single deterministic rasteriser and fixed settings.

Use exactly the same:

```text
page dimensions
pixel dimensions
colour space
background
crop
```

when comparing our renderer.

Keep the original PDF as well as rasterised PNGs.

Where useful, inspect the internal PDF operators/resources rather than treating it solely as a bitmap. It may reveal:

```text
stroke polygons
alpha values
blend modes
patterns
image masks
clipping
texture construction
```

This can substantially reduce guesswork.

---

# Pen fixture corpus

Start by mining existing notebooks in `Drawings`.

Build an inventory of which pens, sizes and colours occur.

Then create a controlled fixture corpus covering every pen/tool actually supported by the connected device and represented in `.rm`.

Do not rely on a hardcoded list from documentation; enumerate the current tool IDs/parser enums and confirm them against real files.

Each pen should have controlled examples covering approximately:

```text
single point / tap
very short stroke
long straight horizontal
long straight vertical
diagonal lines
slow curve
fast curve
circle
zigzag
crossing strokes
dense scribble / shaded region

low pressure
medium pressure
high pressure

slow movement
fast movement

different directions / angles

all available thickness settings
representative colours
multiple overlapping strokes
```

Textured pens need substantially more samples.

---

# Creating fixtures on the tablet

Existing `Drawings` documents are read-only source material.

If controlled fixtures are required, create a dedicated area such as:

```text
Drawings/Renderer Fixtures
```

or uniquely prefixed fixture notebooks.

Any operation that writes to the tablet must be explicit and opt-in, e.g.:

```text
--allow-device-write
```

Never overwrite or delete existing user drawings.

Before implementing a native writer, inspect `SamMorrowDrums/remarkable-mcp` and `librm_lines`, both of which contain relevant authoring/writing work.

Prefer reusing a known-compatible writer rather than manually editing the xochitl store.

If writing directly into xochitl becomes unavoidable:

1. back up the entire target document first;
2. work only with dedicated fixtures;
3. understand required metadata/index files;
4. avoid modifying documents while they are open in xochitl;
5. make every operation reversible.

Do not experiment destructively against normal `Drawings` content.

After a fixture exists on the device:

```text
fixture source
    ↓
tablet
    ↓
raw export (.rmdoc / SSH)
    +
native PDF export
    ↓
local corpus
```

This creates paired input + expected-output data.

---

# Renderer interface

The renderer should ultimately expose something approximately equivalent to:

```ts
renderPage(page, options): Bitmap

renderReplayFrame(page, replayState, options): Bitmap
```

where `replayState` can specify:

```text
visible completed strokes
current active stroke
active point/progress
```

Do not design rendering solely around SVG if SVG starts limiting fidelity.

SVG/resvg is fine as the first backend for simple pens.

For textured pens, a direct raster renderer, Skia-like backend, Rust/native core, WebGPU, or Canvas implementation may be more appropriate.

Make this an evidence-based choice after analysing native output.

---

# Pen rendering investigation

For every pen determine the actual relationships among:

```text
stored point width
thicknessScale
pressure
speed
direction
point spacing
segment length
colour
alpha
overlap
```

Do controlled experiments rather than tuning arbitrary constants against random drawings.

Specifically investigate:

### Simple pens

Ballpoint, fineliner, marker-like tools, etc.

Determine:

```text
width interpolation
cap geometry
join geometry
pressure response
minimum width
anti-aliasing
colour/alpha
```

These should be capable of extremely close geometric matching.

### Calligraphic / directional pens

Determine whether nib orientation depends on:

```text
stroke direction
stored direction value
fixed nib angle
pressure
```

### Pencil / mechanical pencil

This is a priority.

Investigate:

```text
grain/noise source
grain scale
pressure → darkness
pressure → width
speed → darkness or texture
directionality
edge softness
opacity variation
repeated-overdraw behaviour
whether texture is seeded/deterministic per stroke
```

Do not approximate pencil as a grey variable-width polyline and call it finished.

### Brush / paintbrush

Investigate:

```text
pressure-width curve
opacity
edge shape
taper
point interpolation
velocity response
colour mixing/blending behaviour
```

### Shader

Investigate:

```text
alpha model
overlap behaviour
texture/density
blend mode
```

### Highlighter

Verify:

```text
alpha
colour override
blend/composite mode
overlap behaviour
interaction with existing ink
```

### Eraser

Correct replay semantics matter.

An eraser must affect the appropriate ink/layer rather than simply painting background-coloured pixels.

Determine what information survives in the final `.rm` representation and be explicit about historical states that cannot be reconstructed.

---

# Texture determinism

Animations expose renderer instability much more clearly than static pages.

A textured stroke must not generate fresh random grain every frame.

Texture must be a deterministic function of stable inputs, for example:

```text
stroke ID
point/segment index
position
pen parameters
```

so that revealing 60% of a pencil stroke and then 61% does not cause the already-visible 60% to shimmer.

If the tablet itself appears to use deterministic per-stroke texture, attempt to reproduce its seeding/model.

---

# Fidelity comparison tooling

Build comparison tooling as a first-class feature.

For every fixture produce:

```text
native.png
ours.png
absolute-diff.png
high-gain-diff.png
50%-overlay.png
metrics.json
```

Do not depend solely on full-page SSIM because a mostly white page can hide bad stroke rendering.

Calculate metrics both globally and over a padded ink/content ROI.

Useful measurements include:

```text
pixel MAE / RMSE
SSIM
edge distance / geometry error
coverage / ink density
opacity histogram
local darkness distribution
```

For textured pens, consider frequency-spectrum or local texture statistics when literal pixel identity is impossible.

Maintain metrics per pen, not only per page.

---

# Acceptance target

For simple/non-textured pens, aim for essentially indistinguishable geometry and compositing at the chosen reference resolution.

For textured pens, match:

```text
overall shape
stroke width/taper
darkness
pressure response
grain scale
grain density
directionality
overlap
```

before optimising for exact individual noise pixels.

A renderer improvement is valid only if it improves a meaningful fixture set rather than one hand-selected example.

Keep before/after metrics for renderer changes.

---

# Avoid fixture-specific hacks

Do not introduce constants based on page coordinates or individual fixture IDs.

Pen parameters must derive from:

```text
pen type
point data
stroke metadata
document/device dimensions
well-documented calibrated constants
```

Every empirically calibrated constant should have:

```text
a descriptive name
an explanation
the fixture(s) used to infer it
a regression test
```

---

# Device-size correctness

Do not assume every reMarkable page is 1404 × 1872.

Read `SceneInfo.paper_size` and relevant document metadata where available.

Support the actual connected device geometry and keep coordinate transforms explicit.

The core renderer should not bake one model's dimensions into pen behaviour.

---

# Testing strategy

Implement three levels of tests.

### Parser tests

Known `.rm` → expected structured stroke metadata.

### Renderer unit tests

Synthetic normalized stroke → expected geometric/raster behaviour.

### Device golden tests

Real `.rm` + tablet-native PDF export → image comparison.

Golden files should be versioned selectively and accompanied by a manifest describing:

```text
device model
firmware
fixture creation method
pen
size
colour
reference rasterisation settings
```

---

# Development sequence

Execute in this order:

## Milestone 1

SSH `Drawings` discovery and immutable document snapshots.

## Milestone 2

Parse pages and dump complete stroke metadata.

## Milestone 3

Render deterministic stroke-step and progressive-stroke videos using the best existing renderer.

Do not block replay on renderer perfection.

## Milestone 4

USB API provider:
- browse `Drawings`
- download `.rmdoc`
- download tablet-native PDF
- pair them into fixture records.

## Milestone 5

Build automatic native-vs-local raster comparison tooling.

## Milestone 6

Establish controlled fixtures for all pens.

## Milestone 7

Improve simple pen fidelity first so coordinate, width, interpolation and compositing fundamentals are correct.

## Milestone 8

Reverse-engineer and implement pencil/mechanical-pencil fidelity.

## Milestone 9

Brush, shader, highlighter and other textured/special tools.

## Milestone 10

Run the improved renderer through the replay engine and specifically test texture stability during progressive drawing.

---

# Definition of done for Part A

Part A is complete when I can select a notebook/page from `Drawings` and:

1. acquire it over SSH;
2. later acquire the equivalent raw document through the local USB API;
3. parse its native `.rm` strokes;
4. inspect all retained stroke metadata;
5. render the page;
6. generate a deterministic video reconstructing it stroke-by-stroke;
7. optionally animate individual strokes point-by-point;
8. reproduce the same output on repeated runs.

---

# Definition of done for Part B

Part B is complete when:

1. every pen/tool encountered on the connected device has a fixture;
2. every fixture has raw `.rm` input and a tablet-native reference export;
3. renderer comparison is automated;
4. ordinary pens are visually extremely close to native rendering;
5. pencil, mechanical pencil, brush and other textured pens no longer look like generic SVG approximations;
6. texture remains stable across animation frames;
7. renderer parameters are systematic and documented rather than fixture-specific;
8. regressions are caught by golden-image tests;
9. the stroke replay renderer uses the same high-fidelity rendering implementation as static rendering.

---

# Important operating constraints

- Existing content in `Drawings` is read-only.
- Device writes require an explicit opt-in and may touch only dedicated renderer fixtures.
- Do not hardcode SSH credentials.
- Preserve original `.rm` and `.rmdoc` files.
- Do not rewrite raw files merely to parse/render them.
- Do not discard unknown fields unnecessarily.
- Do not claim chronological replay until ordering semantics have been verified experimentally.
- Do not claim pixel-perfect rendering based on visual impression alone; maintain quantitative diffs.
- Prefer existing open-source parsers and learn from existing renderers before implementing replacements.
- Keep acquisition, parser, replay and renderer modular enough that each can be improved independently.

Start by inspecting the connected device, locating `Drawings`, taking a read-only local snapshot of a few representative documents, and establishing the parser/diagnostic pipeline. Then produce the first replay video before beginning renderer reverse-engineering.