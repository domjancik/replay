# Animation milestone acceptance

Checkpoint: 2026-09-24. These are the four milestones authorized in the current conversation, not the original brief's ten-phase numbering. Green unit tests do not establish native rendering fidelity.

| Milestone | Current evidence | Remaining acceptance |
| --- | --- | --- |
| 1. Automatic styled/wrapped/reordered text anchors | Native-assisted matching accepts all 12 controlled cases and both independent dreams groups. CLI `--auto-text-anchors` produces a 426-frame progressive replay without manual offsets; final/static equality passes. Ambiguous/unsupported matches, unresolved ancestors and conflicting shared-anchor offsets reject before output. | A matching native PDF is required. Raw-only typography remains unimplemented; missing history is no longer an established blocker. |
| 2. Simple-pen fidelity | `ecd1547` adds ballpoint width/pressure/speed treatment. On the three-stroke isolated fixture, ROI SSIM improves from 0.941389 to 0.973088 and edge distance from 0.50431 to 0.38154 px. | Held-out pressure/speed/thickness fixtures and other simple tools. The 0.75 raster-width calibration is provisional. |
| 3. Smooth directional reveal | `8d2d9ba` adds initial/inter-stroke/final pauses to interpolated distance reveal. Synthetic 30/60 fps samples contain 156/311 frames; final PNG SHA-256 equals static PNG in both. Sparse/reverse/crossing paths and stable textured prefixes have regression coverage. | Original timing remains inferred. Native texture behavior remains subject to milestone 4 calibration. |
| 4. Stable textures and erasers | `d5ecbe1` implements layer-local destination-out erasing. Pencil/mechanical-pencil/brush profiles now use fixed source-distance deposition and deterministic grain; a 91-frame synthetic texture video ends exactly at static output. Tests cover layer clearing, later ink, pressure response, circular nib direction and no future-stroke leakage. | Profiles are experimental, speed response unmodeled, native grain/density and eraser width/shape fidelity unproven. Collect isolated calibration exports and fit/validate against held-out cells. |

## Inspectable local evidence

Generated/private evidence remains ignored:

- `artifacts/milestone-3-smooth-reveal/{30fps,60fps}/smooth-reveal.mp4`
- `artifacts/simple-pen-ballpoint-profile-v3-comparison/`
- `artifacts/anchor-auto-audit/paired-fit-report.json`
- `artifacts/anchor-auto-audit/per-stroke-residual.json`
- `artifacts/eraser-semantics/native-page1-cross-layer/`
- `artifacts/dreams-auto-anchors-progressive-20260924/`
- `artifacts/milestone-4-texture/`
- `fixtures/private/controlled-anchor-analysis/texture-grid-v1/`

The original native-assisted `dreams` report rejected both group matches. Subsequent worker tests exposed invalid PDF extraction: the original mask ignored nested transforms, clipping, fill rules and white overpaint. Reusing the Poppler comparison path makes both groups pass the unchanged matcher thresholds, with reported forward and reverse coverage of 1.0. The saved `corrected-controlled-and-dreams-report.json` also records accepted matches on all eight v2 anchored cases and all four v3 cases. Corrected `dreams` offsets are 3312.5 and 3728.25, restoring monotonic placement. Root independently inspected the corrected overlay and ran the automatic CLI replay. Independent candidate/native comparison has symmetric edge distance 0.85656 px and ink-ROI SSIM 0.921181. The original report is retained as superseded diagnostic evidence; it does not establish missing historical state.

The natural eraser crossing spot-check also fails to establish fidelity: destination-out changed-region MAE is 162.5 versus 92.5 for legacy white overpaint, and both candidates are white at a native-black crossing. The page has unresolved anchored transforms. This cannot distinguish an eraser-model defect from geometry/association error and must not be used as controlled width calibration.

## Integration gate

Before closing the goal, rerun the relevant full suite, lint, compile and lock checks; inspect native comparisons and progressive samples; verify final/static PNG equality for each backend/options combination exercised; document unresolved tools and historical ordering limitations. The final root offline integration checkpoint passed 134 tests, Ruff, compileall, lock validation and diff whitespace checks including the final matcher guards. The worker also reran all 12 controls and both dreams groups on that final matcher.

The next native calibration batch is prepared as one dedicated 10-page archive: six textured tool variants, three simple pens and a two-layer eraser control. Its manifest maps pressure/width/speed/direction/thickness sweeps and shapes. No upload has occurred. A bounded direct USB probe on 2026-09-24 could not connect to port 80; reconnection is needed to acquire these missing native references. The batch README specifies one acquisition/export session followed by offline calibration.

All four milestones remain in scope. Work proceeds offline until a specific missing observation is established; any future device session should collect the necessary paired raw/native states in one bounded batch.
