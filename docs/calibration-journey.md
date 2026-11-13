# How rm-redraw learned to render a pencil stroke

*Development record for September 2026, reviewed November 13, 2026.*

The portrait's temple looked too dark even after the pencil pressure curve had been fitted to the reMarkable desktop app's PNGs. One diagnostic kept the old pressure curve, brush geometry and paper-grain phase, then changed when the image was reduced to half size. Temple darkness went from **0.669 to 0.524**, against **0.533** in the app export. The beard and shoulder moved in the same direction. Individual strokes had been reduced before they met one another. At that scale, the renderer had already forgotten which fine paper holes several strokes shared.

The experiment depended on earlier corrections to page coordinates, saved stroke order, pen geometry and reference selection. The frozen crop and full-page comparison are recorded in C7 below.

## 1. From saved notebook to an inspectable scene

The first deliverable was a replay from an immutable notebook snapshot. On disk, a visible document name is metadata attached to an ID. Page order comes from document content and can differ from archive or filename order. The acquisition layer reconstructs those relationships, preserves page bytes and hashes, and records how they were acquired. SSH supplies read-only snapshots. USB supplies `.rmdoc` archives and, when available, a PDF from the same notebook. Independent repeat readbacks and ordered page correspondence matter because the drawing can change between exports.

The parser builds on `rmscene` for version 6. It retains the stroke's tool, color and explicit RGBA, raw point position, pressure, speed, direction and width, plus scene groups, CRDT identifiers, moves, tombstones and diagnostics for unrecognized data. The saved scene supports reconstruction of visible stacking. Replay uses a deterministic inferred sequence, with an entry-order option across layers and a bottom-to-top layer-by-layer option. Both use the same bottom-to-top compositing order. Timing is synthesized, and deleted content or prior states may be unrecoverable from the final file.

Page size and the source-to-page affine are separate measurements. A validated 1404-wide portrait uses a +702 X translation, while independently measured 1872-wide scrolling exports used +936 and had much taller canvases. The normalized model carries the evidence for each geometry choice. A centered frame is applied when supported by the paired evidence or supplied by the caller. See C1 below. [Shared contracts](contracts.md)

## 2. The text-anchor hypothesis that failed

Some ink groups move with typed text. Wrapped, styled and reordered paragraphs made simple baseline arithmetic unreliable. The early paired-native matcher appeared to reject two groups on an independently collected scrolling page. Missing attachment history looked like a possible explanation. The failure was in the measurement: a homemade extractor read PDF operands without fully following nested transforms, curves, clipping, fill rules or white overpaint. It had supplied the matcher with the wrong mask.

The replacement reused the Poppler comparison rasterizer and filtered supported direct text objects. The same thresholds then accepted all 12 controlled anchor cases and both groups on the natural page. On that page, both forward and reverse match coverage reached 1.0 at the configured tolerances, and the two fitted offsets followed the logical text order. An independent reparse and render measured 0.857 px symmetric edge distance and 0.921 ink-ROI SSIM against the filtered PDF. The corrected automatic placement drove a 426-frame progressive replay with final/static PNG equality. Raw-only text layout remains open. The automatic path requires a matching PDF, validated canvas and a supported ink-only scope, and rejects ambiguous placement. Evidence C2 · [Comparison contract](contracts.md#comparison)

## 3. Controls before pen parameters

The September 24 capture on tablet firmware 3.28.0.172 paired 19 dedicated control pages with repeated raw and PDF exports. A later three-page supplement isolated taps, short paths and eraser width. The exports preserved ordered page correspondence and repeat stability. All 126 dynamics cells in the main batch had ink. Eleven single-point tap cells and three low-channel cells were white at source resolution and became negative observations. The supplement's first PDF requests timed out. Subsequent bounded requests succeeded after notebook initialization, using the same installed fixture. The final 22-page batch was checked by the actual offline parser, renderer and comparison tools.

Each comparison records geometry, reference rasterizer and settings, target size, crop and hashes. It emits absolute and high-gain differences, an overlay, and full-page and padded union-ink-region metrics. On a sparse sheet, the white margin can dominate a page-level score. Edge distance, ink mass, density, local contrast and spatial variation answer different questions, especially when two pencil textures place their grains at different locations. Evidence C3 · [Comparison contract](contracts.md#comparison)

| Tool | What the controls established | Remaining model limits |
| --- | --- | --- |
| Ballpoint | Isolated controls informed the pressure and edge profile, including a 0.75 width factor. The natural anchor page, withheld from later fitting, stayed byte-identical after the simple-tool and texture work. | That natural regression check contains ballpoint only. |
| Fineliner | Current tool takes the first point's raw width divided by four for the entire path, with round caps and joins. A variable-width candidate failed the ramps. Direct PDF width operators explained why. | The inspected ramp cells were removed from reserved evaluation. At half scale, a small width bias remained in the audit. |
| Marker | A smooth envelope brought the measured width much closer on reserved black-only dynamics. | Native filled polygons have irregular contours. Variable-width interpolation is provisional. |
| Highlighter | Current controls support quarter-unit width, butt caps and bevel joins, measured yellow and channelwise Darken within a layer. | Cross-layer Darken and broader variable geometry remain unverified. |
| Calligraphy | A swept raw-width envelope at fixed 4× pixel centers fixes the earlier thin, hard-edged result. Coverage is area-averaged and source alpha applied once. Reserved-grid mean ink MAE went from 50.31 to 10.32 across 14 cells. | Raw width 96 still gives about 24 source pixels versus 22.125 in the checked export. Directional nib behavior and arbitrary native contours are open. |
| Eraser | Raw widths 8/16/40/80/160 cut 2/4/10/20/40-source-pixel bands independent of thickness. Single and coincident taps had no effect. Short nonzero strokes clear the current layer, and later ink survives. Closed paths clear along their boundary. | Missing-width fallback and variable joins/tapers are provisional. A natural crossing with unresolved anchors could not isolate eraser behavior. |

On the reserved black-only dynamics, fineliner mean ink ROI MAE fell from 36.92 to 4.52 (15 cells) and marker from 27.21 to 4.52 (18 cells). The measured basic palette included gray `(144,144,144)`, red `(194,49,50)`, blue `(48,74,224)`, and highlighter yellow `(254,253,96)`. Separating hue from geometry made it possible to attribute those black-only gains. Evidence C3 and C4.

## 4. Texture, coverage and what pressure actually changes

The early textured model replaced flat gray with deterministic deposition. In the inspected PDF controls, brush mean ink MAE improved from 138.45 to 61.32, while pencil moved from 93.32 to 96.70. Pencil ink mass and contrast improved even as the pixel score worsened. A test that split coarse boundary coverage from fine interior grain got one edge-variation statistic almost right, but damaged the interior. Edge variation went from 1.217 to 2.006 against 1.986 in the PDF raster, while interior contrast went from 91.66 to 73.61 against 96.10. The candidate was dropped. The PDF showed opaque filled paths in the inspected cases. A two-scale grain model was a hypothesis about the appearance.

Repeated strokes supplied a stronger clue. At one, three and nine coincident pencil strokes, one PDF control measured relative ink masses of 1.000/0.999/1.059. The older renderer measured 1.000/1.974/2.422. Sharing a source-coordinate paper field brought the candidate to 1.000/1.460/1.720. Distinct strokes can reuse the same fine paper holes. Ordinary source-over still applies, and coverage at partly covered pixels can still build up. A same-pigment maximum-alpha trial could not distinguish shared coverage from real source translucency. A separate blanket 2× page-composition trial improved one density measure while worsening page MAE and SSIM. Both were rejected at that stage.

A pressure curve fitted to five earlier fixed-width controls was frozen before an independent eight-page capture was scored. It crossed nine pressures, six actual path angles, three widths and both current pencil tools, with additional direction, sampling, ramp and overdraw cells. Across 432 cells, mean source-normalized absolute ink-mass error fell from 58.594 to 38.116 at full size and from 65.116 to 47.089 at half size. At full size 312 cells improved, 52 regressed and 68 tied. Low-pressure broad strokes still deposited too much. Some angle and stored-direction examples occupied different paper positions, making local grain phase a confound. A later sparse-boundary profile improved the outline-variation score while slightly worsening aggregate errors. It remains an opt-in comparison profile. Evidence C4 and C5.

## 5. The export target changes the answer

The desktop app PNG and the USB PDF raster of the same portrait had almost identical full-resolution global densities, 0.36647 and 0.36650. Yet background-region darkness was 20.75/255 in the app PNG and 4.45/255 in the PDF raster. A face region measured 54.76 and 38.01. Rasterizing the PDF directly at half size introduced its own density change, and rasterizing at full size then reducing it still left local differences. Poppler Splash and Cairo both differed from the app image. Cairo flagged an undefined initial PDF graphics state. Its effect and the reason for the export-path differences remain unresolved.

The app PNG became the full-size appearance target for the next pencil and brush fit. The USB PDF remained valuable for transforms, caps, widths, paint operators and export-specific comparisons. Tablet PNG caches at 384×512 gave an automated tonal cross-check. On the portrait at that common size, the tablet cache had mean absolute RGB error 6.98 against the area-reduced app PNG, versus 27.78 for the area-reduced USB PDF raster. Cache freshness was unproven. The verified full-resolution route was the desktop app's batch PNG export.

The next notebook combined 31 existing reference pages with eight physical worksheets, then paired all 39 desktop PNGs with matching desktop and tablet raw pages. It captured pencil, mechanical pencil, calligraphy and paintbrush at approximate human tilt and pressure targets. The 68 mapped cells used translated guide geometry and excluded guide ink from the measurements. At firm-pressure targets the pencil's median raw width moved from 24 upright to 62 at low tilt, while median pressure stayed 253. That supports using the observed width. The analysis did not establish that the stored direction channel directly encodes tilt or justify adding a second width multiplier. Evidence C6.

## 6. The difference between adding grain and preserving it

The first desktop-PNG fit used 27 horizontal pencil pressure cells and five brush pressure cells. The pencil gained fine shared grain, a separate edge field and sparse pinholes at full pressure. Brush gained broken low-pressure coverage and irregular antialiased edges. Across 507 reserved pencil cells, mean absolute mass error fell from 39.114 to 20.021 and union-ink pixel MAE rose from 122.103 to 163.542. A nine-repeat mass ratio of 1.7069 moved to 1.0549, near the app's 1.0494. Across 46 reserved brush cells, mass error fell from 230.057 to 138.577 and ink ROI MAE fell from 56.617 to 42.773. Many reserved cells were examined in earlier phases. They were excluded from this fit and the natural portrait was excluded from every fit described here.

The dark regions of the portrait motivated an isolated comparison with the prior profile frozen. The source-resolution path restored absolute paper phase, composited the layers and reduced the completed image once with a BOX filter. All three tested regions moved substantially toward the app's darkness and had lower pixel MAE. Minor floating-point differences between translated diagnostic crops and the earlier full-page result were measured separately, below 0.01 channel units on average. Evidence C7.

### A two-sample example

Each tile below is a source sample. Two black strokes hit the same left sample and leave the same right sample white. The output pixel averages the pair.

| Operation | Sample coverage | Output darkness |
| --- | --- | ---: |
| Stroke A or B alone | `■ □` | 50% |
| Composite both at source, then BOX-reduce | `■ □` | **50%** |
| BOX-reduce each stroke, then composite the two 50% opacities | `◩` over `◩` | **75%** |

For same-color source-over, combined opacity is `a + b − ab`. The product depends on whether both strokes cover the same fine samples. Averaging each mask independently loses that relationship. The two-sample example is synthetic and follows directly from the equation. [Renderer contract](contracts.md#replay-and-rendering)

The current default adds a weak four-source-unit field over the pencil's one-unit grain, while brush uses correlated 1.5-source-unit clusters with fine variation. On a pressure-64 brush control the old result had 21 blank columns and 49 opaque pixels. Clustering moved those counts to 69 and 66, against app counts of 86 and 71. The original-resolution reserved pencil mass error slightly worsened from 20.0208 to 20.6395 and pixel MAE was essentially flat. The reserved brush errors improved slightly. Physical results were mixed. Clustering changes the appearance and statistics of individual marks. Compositing at source resolution addressed the much larger overlap problem.

| Portrait result at 702×936 | Before | After | Desktop app PNG, BOX-reduced |
| --- | ---: | ---: | ---: |
| Global density | 0.417645 | **0.369182** | 0.365542 |
| Temple density | 0.66864 | **0.52433** | 0.53265 |
| Beard density | 0.63841 | **0.55162** | 0.56498 |
| Pixel MAE against app | 44.258 | **41.580** | — |
| SSIM against app | 0.30555 | **0.30680** | — |
| Symmetric edge distance against app | **0.71365 px** | 0.72487 px | — |

This final page comparison includes clustering and the composition change. The frozen-region experiment isolates the latter. Remaining structure is visible in the pixel and edge results even where density is close. Legacy tools, the shader, arbitrary directional calligraphy and broader firmware and device coverage remain outside the validated fit. Evidence C7.

## 7. Fast enough to use, with the same pixels

The replay renderer first learned to cache an exact completed compositing prefix. Lower layers and the current layer are retained separately. An active stroke is drawn into a disposable copy. Backwards states rebuild, and nonprefix states can use the stateless path. On a 12-frame slice over the first 384 strokes of a drawing, render time went from 97.75 to 15.04 seconds. Static output serves as an independent equality check.

Source-resolution composition raised the cost of a small output from a large source page. A subsequent byte-preserving pass cached pressure-independent float64 paper fields in bounded source-phase tiles and clipped stroke-local alpha buffers on whole-pixel boundaries. All 14 control pages, 585 cells, 576 additional texture cases and 111 progressive golden PNGs matched the preceding Python output. The full portrait went from 966.52 to 261.53 seconds in the recorded runs. Fresh paired 14-page control timing fell from 28.44 to 17.47 seconds.

Profiling the optimized portrait put 95.2% of render time inside pencil deposition, including NumPy work. The optional Rust kernel takes one reached stroke per C ABI call and fuses distance, edge, grain threshold and max-union work within that stroke. The host retains the calibrated pressure arithmetic. On the local Windows x86-64 build, the full portrait took 103.71 seconds against the earlier 261.53-second optimized Python run, about 2.52× faster. Paired small samples ranged from 1.66× to 3.52× depending on stroke width and cache state. The port matched the tested Python output exactly, including the complete portrait, all 14 control pages and all 111 progressive golden frames. These are local timing and parity results. Full-scene replay throughput and WASM performance remain unmeasured by this experiment. Evidence C8.

## 8. From the calibration bench to a loop

The local replay utility imports `.rmdoc` files or reads a USB notebook and optionally pairs a PDF for anchors. It can synthesize a fixed drawing duration, reveal partial strokes directionally, and retain a fixed viewport. The grain is determined by source coordinates and stable stroke inputs so earlier parts of a line stay put. A completed replay must match the independently rendered static PNG byte for byte under the same options.

Crop and reverse-loop exports reuse saved lossless frames. One even-pixel rectangle applies to every frame and the static PNG. The final forward frame matches cropped static output. The optional 2×, 4× or 8× reverse skips the repeated final hold and returns to the first frame, matching the loop seam. These checks concern lossless source frames. H.264 is a lossy delivery format. [Local replay utility](local-replay-utility.md) · [Crop and loop contract](contracts.md#corpus-layout)

## 9. November follow-up on natural pages

Two notebooks read on firmware 3.29.1.0 supplied three further comparison pages. Repeated raw member hashes, decoded PDF page streams and Poppler pixels matched for both notebooks. Visual checks established correspondence on the three selected pages. A separately attempted mixed-tool notebook remains unpaired after its PDF export timed out.

Two pages had 145 and 477 fineliner strokes. Their raw base canvas was 1404×1872 even though ink extended below that height. PDF bounds and the measured PDF transform supplied explicit inferred canvases of 1404×2273 and 1404×4326. The ink aligned visually across both scrolling pages. Template dots remained in the PDF and contributed heavily to the edge-distance metric. The mixed page had 690 calligraphy, 146 current pencil and nine other strokes. It measured ink-ROI MAE 11.11 and SSIM 0.865 at 352×468 against its USB PDF raster, with visible texture and darkness differences. Those numbers describe the PDF reference and preview resolution.

All three natural pages produced 84-frame entry-order replays at 12 fps, with six seconds of synthesized drawing and a one-second hold. Each final lossless PNG matched the corresponding static file. The mixed-tool replay used the optional Rust pencil kernel. These cases add consumer, viewport and final-state evidence on newer firmware. The comparison does not cover desktop PNG appearance, the uncaptured mixed notebook, full-resolution geometry, or wider tool behavior. Evidence C9.

## Evidence and images

In the development checkout, the local illustrated annex is `artifacts/publication-20261113/index.html` when the private evidence is present. It shows the corrected anchor overlay, simple-pen controls, pressure matrix, the PDF/app target difference, physical tilt sheets, source-composition crops, the full portrait comparison and progressive frames. Its private drawing and device-derived controls require separate permission before redistribution. The two-sample example above can be reproduced without a tablet or private inputs.

| Evidence | Record in the development archive | Implementation checkpoint |
| --- | --- | --- |
| C1 · Acquisition and geometry | Kickoff verification, snapshot manifests, paired canvas comparison | `6f02a29`, `ca66857` |
| C2 · Anchor correction | Corrected automatic anchor report, independent ink-only comparison and replay manifest | `42108ed`, `820b56f` |
| C3 · Controlled pen geometry | September 24 capture readiness, tap and eraser readbacks, simple-pen split and per-cell report | `0c2bb83`, `1b06628` |
| C4 · Early texture and calligraphy | Texture v2, dual-scale trial, coverage v4 and calligraphy calibration | `a4e3fa6` |
| C5 · Pressure and sparse boundaries | Frozen pressure/angle validation, sparse-boundary experiment | `e70b22a`, `3db9f95` |
| C6 · Export qualification | App/PDF audit, cache comparison, 39-page app PNG pairing and physical-worksheet channel audit | `d8f5820`, `e36afe2` |
| C7 · App fit and composition | Frozen PNG fit and cluster validation, phase-restored region diagnosis and full natural-page report | `7558f35`, `fdaa8e7` |
| C8 · Runtime and parity | Paired control timing, full-page profiling, Python and Rust equivalence reports | `404e3b8`, `5150a2b` |
| C9 · November natural pages | Repeat readback validation, three corrected PDF comparisons and three progressive replay manifests | November 13, 2026 |

The [renderer landscape](renderer-landscape.md) describes contemporary alternatives and what a common-input benchmark would measure.
