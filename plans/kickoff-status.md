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
| Geometry follow-up | GPT-5.6 Sol, high | Evidence-carrying geometry resolver, unknown-transform correction, page-2 outlier diagnosis |
| Independent acquisition | GPT-5.6 Terra, medium | Three immutable SSH snapshots, 27 v6 pages, validated hashes; no paired native exports |
| End-to-end replay | GPT-5.6 Terra, high plus coordinator review | Local `.rm`/`.rmdoc` CLI, deterministic frames/static/manifest/H.264, encoded-timeline and equality gates |
| Native comparison tooling | GPT-5.6 Terra, medium plus coordinator review | Supported PNG/PDF comparison CLI, fixed Poppler rasterization, global/ink-ROI/edge metrics, diffs and overlay |
| Source-affine evidence audit | GPT-5.6 Sol, high | Same-device `+702` convention strongly supported; evidence remains too narrow for an automatic parser default |

Acquisition verification fixture: `fixtures/private/verification/8aba68ff-00e9-400b-9772-b96322e000f0/` (ignored). The USB archive and five-page native PDF pass structural checks. Poppler rasterized five 890×1188 PNGs at 144 DPI. It emitted non-fatal unknown `ExtGState GSa` warnings.

Complete SSH snapshot: `fixtures/private/verification/ssh-v3/8aba68ff-00e9-400b-9772-b96322e000f0/` (ignored). Its manifest records firmware `3.27.3.0`, build `5.7.126 (scarthgap)`, machine `reMarkable Chiappa`, five ordered page IDs, three sidecars and five `.rm` files. All local sizes/hashes match, every file records size/mtime stability, and every SSH `.rm` is byte-identical to its USB archive member.

The older ignored `ssh/` snapshot is intentionally retained as incomplete diagnostic evidence; it predates support for current `cPages.pages` metadata and contains only sidecars. `ssh-v2/` is complete but predates device-provenance fields. Neither is a valid canonical snapshot; use `ssh-v3/`.

`rmscene 0.8.0` parsed all five real v6 pages: 10,494 strokes and 312,252 points total, with zero unreadable blocks, unparsed extras or adapter warnings. The sample exposes tool codes 6, 13–17 and 21, and colours 0 and 2. `SceneInfo.paper_size` is absent on all five pages. The library discards a line-internal tag-6 timestamp; the exposed CRDT item ID remains available, and replay order remains explicitly labeled as an unverified deterministic fallback.

The first anchored-group implementation used the community `rmc` text-layout constants. User review correctly found that the layers were still vertically displaced. Five-page comparison against the paired native PDF isolated the problem to anchored content: the unanchored base layer already aligned, while every page's anchored content needed about 145 source units of Y correction. A fixture-calibrated origin of `text.pos_y + 63` and 69.5-unit plain-paragraph spacing reduces whole-page residual Y registration from 145.2–145.9 source units to -0.2–1.0 across all five pages without moving unanchored ink. Mean candidate-centerline distance to native ink falls from 8.04 to 1.23 pixels, and the fraction within three pixels rises from 57.6% to 91.0%. Before/after overlays and per-transform measurements are under the ignored fixture `diagnostics/` directory. Of the 312,208 points included in the per-transform diagnostic, one page-2 transform containing 1,805 of 57,447 page points remains a 260-unit outlier against the flattened native PDF; the remaining 310,403 measured points are within four source units. This calibration is proven only for the paired notebook and its empty plain-paragraph anchors.

The render projection now retains top-level layer visibility. Static rendering and all replay schedules omit hidden layers. Replay scheduling completes visible layers in final bottom-to-top compositing order and preserves the parser's inferred order within each layer; global CRDT order no longer interleaves layers. A direct module smoke check scheduled all 10,494 real-fixture strokes layer-major across the five pages, and page 1's completed replay frame was byte-identical to its static Pillow render. All layers in this fixture are visible, so hidden-layer behavior is verified with synthetic tests. Final compositing order remains unchanged.

Native-exact rendering remains unclaimed. Page geometry and the `+702` horizontal source translation are still supplied explicitly, the native PDF is flattened so individual native layer rasters are unavailable, and the Pillow baseline does not reproduce pressure, textured tools, or eraser semantics.

Shared contract v2 removes the parser's former silent identity transform. `source_to_page_transform` is now `null` when no source evidence exists. `resolve_page_geometry` combines parsed values with explicit caller overrides, validates both values, and records separate evidence for page size and affine transform. The pipeline and replay command fail actionably when geometry remains unresolved. An independent scan of 27 pages found 11 with `SceneInfo.paper_size=(1404,1872)`, 16 without page size, and none with a source affine transform; no page resolves fully without an explicit transform.

The earlier page-2 `1:24` 260-unit result is classified as a flattened-PDF matching ambiguity. Tight objectives select 0–2 units, adjacent anchors `1:23` and `1:25` align at zero, and the broad capped-mean preference for 260 improves the score by only 0.004451 pixels while reducing the fraction within two pixels. Evidence is under the ignored `diagnostics/page-2-anchor-1-24/` directory.

The local replay command is available through `python -m rm_redraw.replay`. It accepts a local `.rm` page or selected `.rmdoc` member, explicit geometry when needed, all three scheduling modes, FPS and viewport controls, and a fresh output directory. It emits hashed PNG frames, `static.png`, H.264 `replay.mp4`, and `manifest.json`; frame timestamps use the encoded FPS, and completion requires final/static byte equality. The ignored inspection sample at `artifacts/sample-replay-546a0d59-progressive/` contains 60 progressive frames at 280×376, a two-second H.264 video, and a byte-identical final/static PNG. Its `+702` transform is caller-supplied from the first paired fixture and is not independently proven for that page.

Follow-up read-only acquisition created three immutable SSH snapshots under `fixtures/private/independent-validation/ssh-v1/`: 27 v6 pages with validated manifest sizes and SHA-256 hashes. The USB API was connection-refused during this follow-up, so these snapshots have no paired native PDF. They contain no anchored groups and only one typed character, so they validate parser/replay breadth and geometry failure semantics but provide no evidence for or against the `+63` anchor origin or 69.5-unit plain-paragraph spacing.

A renewed USB check plus two bounded retries were actively refused on `10.11.99.1:80`. Read-only SSH inspection found no port-80 listener or HTTP/web-interface process; SSH and xochitl remained healthy, and no process was restarted or tablet setting changed. A read-only scan covered all 58 immediate non-deleted notebook children of Drawings. The best independent validation target is `dreams` (`d1c4c1ae-78cb-4fe4-9873-3eae049df7a8`), page `a709e2d0-f34c-4e61-8878-e531e9aab80c`: 48 typed paragraphs including non-plain style 2, two anchored groups, 48 strokes and 1,886 points. The ignored private probe has SHA-256 `D4426567A68EF7E8F6658B4D95A68AAD09F28EE595643C872C1FCA7926D6C068`. It is ready for paired export as soon as the web interface is listening again.

The supported comparison command is available through `python -m rm_redraw.comparison`. It accepts a candidate PNG plus a same-size native PNG or selected native PDF page, rejects implicit resize/crop/colour conversion, and writes normalized inputs, absolute/high-gain differences, overlay, and schema-versioned metrics with hashes and rasterization provenance. A full-resolution 1404×1872 run against the current paired page, using the explicit `(1, 0, 0, 1, 702, 0)` affine, produced global SSIM 0.7652, ink-ROI SSIM 0.7295 and 1.652-pixel symmetric mean edge distance. Visual review shows the main geometry aligned; most residual error is the Pillow baseline's darker, coarser stroke and shading treatment. Evidence is under ignored `artifacts/comparison-current-page1-full/`.

The source-affine evidence audit covered 32 v6 pages across four documents. All 11 available `SceneInfo.paper_size` values are 1404×1872, all four document metadata sets independently record the same dimensions and a `(0, 936)` custom-zoom center, and none of the parsed pages carries an affine. Paired native registration selects `tx=702` on the one repeated coordinate sequence, with per-page estimates of 702–702.25 and a large improvement over identity. This strongly supports a centered source-coordinate convention for the sampled device, but the five paired pages repeat one geometric sample and best-fit metadata may be inactive. The parser therefore keeps the transform unknown until a second paired document or a distinct width/orientation provides independent evidence.

## Recommended model allocation

| Task | Model and effort | Price/performance reason |
| --- | --- | --- |
| USB listener probe and known-command retries | GPT-5.6 Luna, medium | Cheapest choice for short, deterministic checks; escalate the same thread if evidence becomes ambiguous |
| Read-only paired acquisition and corpus inventory | GPT-5.6 Terra, medium | Best default for bounded shell/API work with validation and structured manifests |
| Parser, anchor calibration, affine inference | GPT-5.6 Sol, high | Worth the higher rate for format ambiguity, competing geometric hypotheses and evidence-sensitive conclusions |
| Comparison CLI, diagnostics and routine renderer changes | GPT-5.6 Terra, medium | Strong implementation value for well-frozen contracts and focused tests |
| Cross-module integration and adversarial review | GPT-5.6 Sol, high | Use when failures span parser, replay ordering, rendering and provenance contracts |
| Simple-pen fidelity | GPT-5.6 Sol, high | Requires visual/algorithmic judgment but has a bounded tool model and measurable target |
| Pencil/brush texture research or a stalled geometry investigation | GPT-6 Astra, high | Reserve the premium model for the hardest open-ended research where Terra/Sol evidence has stopped converging |
| Documentation, manifest summaries and repetitive report refreshes | GPT-5.6 Luna, medium | High-volume, low-ambiguity work benefits most from the lowest rate |

The allocation uses current API pricing as a relative cost proxy: Luna is $0.20 input/$1.20 output, Terra $2/$12, Sol $4/$20, and Astra $10/$50 per million tokens. Codex plan metering may differ from direct API billing.

## Next coordination queue

1. Re-enable the tablet web interface, then acquire a paired `.rmdoc`/native PDF export of the identified `dreams` page without modifying tablet content.
2. Run the supported parser/replay/comparison path on that independent anchored, styled-text sample and decide whether the anchor constants generalize.
3. Use the second paired document to retest the centered-coordinate inference before considering an evidence-backed geometry default.
4. Treat eraser semantics and textured pens as known Pillow-baseline limitations while beginning simple-pen fidelity work.
5. Build controlled fixture tooling only after explicit device-write opt-in. Then assign simple-pen work to Sol high and pencil/brush research to Astra high.

Official runtime references: [CPython version status](https://devguide.python.org/versions/), [Python 3.13.15](https://www.python.org/downloads/release/python-31315/), and [uv Python version management](https://docs.astral.sh/uv/concepts/python-versions/).
