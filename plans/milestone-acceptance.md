# Animation milestone acceptance

Checkpoint: 2026-09-24. These are the four milestones authorized in the current conversation, not the original brief's ten-phase numbering. Green unit tests do not establish native rendering fidelity.

| Milestone | Current evidence | Remaining acceptance |
| --- | --- | --- |
| 1. Automatic styled/wrapped/reordered text anchors | Native-assisted matching accepts all 12 controlled cases and both independent dreams groups. CLI `--auto-text-anchors` produces a 426-frame progressive replay without manual offsets; final/static equality passes. Ambiguous/unsupported matches, unresolved ancestors and conflicting shared-anchor offsets reject before output. | A matching native PDF is required. Raw-only typography remains unimplemented; missing history is no longer an established blocker. |
| 2. Simple-pen fidelity | `ecd1547` adds ballpoint width/pressure/speed treatment. On the three-stroke isolated fixture, ROI SSIM improves from 0.941389 to 0.973088 and edge distance from 0.50431 to 0.38154 px. Repeated native captures now cover channel sweeps, dynamic paths and current-tool taps. | Fit and validate against the newly captured controls, including other simple tools and palette differences. The 0.75 raster-width calibration is provisional. |
| 3. Smooth directional reveal | `8d2d9ba` adds initial/inter-stroke/final pauses to interpolated distance reveal. Synthetic 30/60 fps samples contain 156/311 frames; final PNG SHA-256 equals static PNG in both. Sparse/reverse/crossing paths and stable textured prefixes have regression coverage. | Original timing remains inferred. Native texture behavior remains subject to milestone 4 calibration. |
| 4. Stable textures and erasers | `d5ecbe1` implements layer-local destination-out erasing. Pencil/mechanical-pencil/brush profiles now use fixed source-distance deposition and deterministic grain; a 91-frame synthetic texture video ends exactly at static output. Tests cover layer clearing, later ink, pressure response, circular nib direction and no future-stroke leakage. New paired controls expose the provisional eraser width/tap defects and support an offline correction. | Texture profiles are experimental, speed response unmodeled, and native grain/density unproven. Fit and validate against the captured cells; distinguish measured constant-width eraser behavior from unverified variable-width joins/tapers. |

## Inspectable local evidence

Generated/private evidence remains ignored:

- `artifacts/milestone-3-smooth-reveal/{30fps,60fps}/smooth-reveal.mp4`
- `artifacts/simple-pen-ballpoint-profile-v3-comparison/`
- `artifacts/anchor-auto-audit/paired-fit-report.json`
- `artifacts/anchor-auto-audit/per-stroke-residual.json`
- `artifacts/eraser-semantics/native-page1-cross-layer/`
- `artifacts/dreams-auto-anchors-progressive-20260924/`
- `artifacts/milestone-4-texture/`
- `fixtures/private/controlled-anchor-analysis/texture-grid-v2/`
- `fixtures/private/controlled-anchor-analysis/capture-20260924/`

The original native-assisted `dreams` report rejected both group matches. Subsequent worker tests exposed invalid PDF extraction: the original mask ignored nested transforms, clipping, fill rules and white overpaint. Reusing the Poppler comparison path makes both groups pass the unchanged matcher thresholds, with reported forward and reverse coverage of 1.0. The saved `corrected-controlled-and-dreams-report.json` also records accepted matches on all eight v2 anchored cases and all four v3 cases. Corrected `dreams` offsets are 3312.5 and 3728.25, restoring monotonic placement. Root independently inspected the corrected overlay and ran the automatic CLI replay. Independent candidate/native comparison has symmetric edge distance 0.85656 px and ink-ROI SSIM 0.921181. The original report is retained as superseded diagnostic evidence; it does not establish missing historical state.

The natural eraser crossing spot-check also fails to establish fidelity: destination-out changed-region MAE is 162.5 versus 92.5 for legacy white overpaint, and both candidates are white at a native-black crossing. The page has unresolved anchored transforms. This cannot distinguish an eraser-model defect from geometry/association error and must not be used as controlled width calibration.

## Integration gate

Before closing the goal, rerun the relevant full suite, lint, compile and lock checks; inspect native comparisons and progressive samples; verify final/static PNG equality for each backend/options combination exercised; document unresolved tools and historical ordering limitations. The final root offline integration checkpoint passed 134 tests, Ruff, compileall, lock validation and diff whitespace checks including the final matcher guards. The worker also reran all 12 controls and both dreams groups on that final matcher.

The expanded native calibration batch was uploaded once as a new dedicated 19-page notebook on 2026-09-24. It contains textured and simple-tool grids, calligraphy, highlighter, dynamic channel/overdraw/color/spacing controls and two eraser pages. Two raw exports have identical member contents; two native PDFs have identical page streams and identical independently rasterized pixels on all 19 pages. The device rewrote the document UUID, which is recorded with source/export hashes in the ignored capture provenance. Capture firmware is 3.28.0.172, distinct from the earlier 3.27.3.0 references.

The earlier port-80 failure was caused by the restricted network execution context; a permitted read-only probe succeeded. Do not diagnose device disconnection from a sandbox failure. Upload acceptance, page count and repeat stability alone are not capture readiness: cell-level native coverage, geometry and actual offline consumer checks must pass. The native eraser pages have different export bounds; independent PDF-transform and control checks establish +936 X translation and approximately 1872-by-5186/5744 source canvases. Reusing the other pages' +702 translation would be wrong.

The main batch's 126 dynamics cells are nonblank. Eleven single-point tap cells and three low-channel grid cells are exactly white at full source resolution, so they are measured negative cases, not positive coverage. A second dedicated three-page fixture adds stationary/short-path controls and independent eraser width/thickness sweeps. Its initial native exports timed out; later exports succeeded after notebook initialization and a longer bounded request. Both successful raw/native readbacks are stable, and all 22 captured pages have source correspondence, native geometry, visual inspection and actual offline parser/render/comparison evidence. A captured pencil page also passes the CLI progressive replay and final/static PNG equality checks (34 frames).

The captured eraser sweeps establish raw width divided by four, independent of thickness: widths 8/16/40/80/160 produce 2/4/10/20/40-source-pixel vertical bands. One-point and two-coincident-point erasers have no effect; short nonzero paths do. Layer isolation, later ink survival and boundary-only clearing of closed paths are supported. These observations expose defects in the previous provisional renderer and support an offline correction.

The ignored `capture-20260924/readiness.json` records accepted scopes and explicit limits. Saved pairs support the listed grid/dynamics, current-tool tap and eraser calibration work without an active device. They do not prove universal device independence: legacy pencil/brush minimum-sample behavior, arbitrary unknown tools, raw-only typography and historical timing remain outside that claim. Legacy two-point paths can be blank despite dense paths rendering. The prepared width-only fallback was not uploaded because the original supplement eventually exported successfully.

All four milestones remain in scope. Work proceeds offline until a specific missing observation is established; any future device session should collect the necessary paired raw/native states in one bounded batch.
