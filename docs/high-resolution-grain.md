# Experimental high-resolution pencil grain

The optional `high_res_grain` mode addresses visibly square grain cells at enlarged
output sizes. It applies to current pencil/mechanical pencil at **2x source
resolution or higher**, defaults off, and is explicitly an aesthetic departure
from the calibrated reconstruction. It does not claim new native fidelity.

Two smooth, area-preserving shears curve the occupancy-cell boundaries. The
pressure knots, coarse gain field, stroke geometry and edge treatment stay in
place. Grain occupancy is decided consistently at output-pixel centers across
strokes; geometric edges still use supersampling. A per-stroke, lazily populated
u32 cache avoids repeatedly evaluating the shear, costing four additional bytes
per bounded output pixel for the optional pencil path. Other tools are unchanged.

## Validation (2026-11-15)

Compared the calibrated default against the variant at 1x, 2x and 4x using 54
controls: pressures 16, 32, 64, 128, 192 and 255; widths 8, 20 and 32; horizontal,
diagonal and vertical strokes; and overlapping strokes. The wider Rust regression
also checks monotonic pressure response, twenty-stroke overdraw, cache invalidation,
other tools and final replay/static equality. Outputs below 2x are unchanged.

The shaded portrait crop retains all intersecting strokes and layer overlap:

| Output scale | Integrated ink change | Default / refined native time |
| --- | --- | --- |
| 2x | +0.217% | 19.6s / 22.0s |
| 4x | -0.038% | 61.5s / 59.7s |

Times are single local runs, not a browser/mobile performance claim. The crop is
192 source units square; this is not a full-page benchmark. Controls at pressure
32 and above stayed within 2.63% ink mass. The sparsest pressure-16, width-8 mark
changed by 11.47% at 4x, but that is only **0.59 source-pixel equivalents** of ink
(5.13 to 5.72). Finite sparse marks are not density-identical; the pressure function
is unchanged. The option is therefore experimental and never silently enabled.

The rejected first candidate antialiased grain within each stroke. Repeated alpha
composition filled holes and increased portrait ink by 20.5% at 2x. The revised
shared occupancy decision fixes this; retained artifacts distinguish the candidates.
At 1.5x, a pressure-32 control drifted 5.22%, so the option is deliberately inactive
below 2x rather than loosening that acceptance threshold.

All 114 default WASM golden cases remain byte-identical. Rust/WASM replay tests
verify the completed refined frame equals its static counterpart.

## Reproduce

Build `native/redraw` release binary, then run:

```powershell
.venv/Scripts/python.exe scripts/compare_high_res_grain.py --output artifacts/high-res-grain-check
```

The script now also includes a 1.5x unchanged control. Optional `--renderer` selects
a built binary. The synthetic corpus needs no device. If the existing ignored
portrait request exists, the script also evaluates that private crop. Generated
comparisons, raw inputs, metrics and provenance stay under ignored artifacts.
Reference labels mean the **calibrated renderer**, not an app-exported PNG.

Retained accepted comparison: `artifacts/high-res-grain-v2/portrait-comparison.png`
and `pressure-comparison.png`, with `metrics.json`. Rejected first pass is under
`artifacts/high-res-grain/`. The original source-coordinate square cells remain the
default for native-fidelity work.
