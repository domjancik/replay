# Renderer profiling and optimization priorities

Measured 2026-09-25 against commit `404e3b8`, using the complete 2,655-stroke birthday page plus 24 natural pencil strokes and four synthetic broad strokes. This is an analysis pass; renderer code is unchanged.

## Full-page measurements

The full page took 303.605 seconds under cProfile. The preceding unprofiled measurement was 261.531 seconds; profiler overhead means these times are not evidence of a regression. Parsing took 1.104 seconds outside the render timer; PNG writing took 0.034 seconds. The profiled PNG is byte-identical to the accepted golden.

| Area | Cumulative seconds | Share of profiled render | Interpretation |
|---|---:|---:|---|
| Pencil deposition (`pencil.dab`) |289.074|95.2%|Primary target: 1,670,884 dabs |
| Tile-region traversal, lookup and field generation |21.811|7.2%|Nested inside deposition; not additive to its row |
| Pressure occupancy interpolation |8.805|2.9%|Nested inside deposition |
| Generating missing paper fields |4.752|1.6%|Nested inside tile traversal |
| Pillow resizing |0.605|0.2%|Low priority; preserve source-resolution composition |
| Pillow native alpha composition, self time |0.073|0.02%|Not the dominant cost |

There were 2,970,295 cache hits and 3,697 misses: 99.876% hit rate. Retained arrays occupied exactly 24 MiB. Increasing the cache cannot remove the main workload. The workload generated approximately 2.97 million cache-tile patch operations and 135 million profiler-reported function calls overall, including built-in/native calls and generator resumes; this is not a count of exclusively interpreted Python calls.

The 227.449 seconds of `dab` self time must NOT be interpreted as Python interpreter overhead. NumPy ufunc arithmetic executed in native code is also attributed to this function. cProfile alone cannot divide this time accurately between dispatch, allocation, memory bandwidth and arithmetic. No Rust speedup factor follows directly from it.

## Per-stage measurements

An isolated, temporary AST-instrumented copy of the unchanged pencil function measured representative samples without modifying production files. Both outputs remain byte-identical to the baseline. Timers add overhead; these samples are not a weighted breakdown of the entire birthday page.

| Stage | Natural 24 strokes (2.264s total) | Broad 4 strokes (3.993s total) |
|---|---:|---:|
| Distance calculation (`hypot` plus coordinate differences) |0.453s|1.371s|
| Edge coverage |0.284s|0.500s|
| Grain threshold arithmetic |0.249s|0.600s|
| Coverage multiplication, rounding and conversion |0.307s|0.678s|
| Coordinate vectors |0.210s|0.124s|
| Boundary amplitude arithmetic |0.085s|0.238s|
| Maximum update into stroke mask |0.078s|0.091s|

Multiple temporary arrays and full passes over each patch are created for distance, boundary, edge, threshold and coverage. Some passes operate on pixels that ultimately deposit no ink. The fixed half-source-unit sample interval also makes neighboring dabs revisit overlapping regions. These are code-level observations; avoided-work savings have not yet been measured with a replacement algorithm.

## Optimization classification

| Priority / change | Specific to current Python implementation | Language-independent opportunity / constraint |
|---|---|---|
| 1. Fused compiled pencil kernel | Removes Python per-dab/patch calls, NumPy dispatch and chains of temporary arrays | Compute coverage and update the mask in one pass, minimizing memory traffic; preserve float64 calculation order and rounding |
| 2. Batch reached dabs by tile within each stroke | Reduces generators, locks, tuple/view construction and LRU lookups | Better locality and field reuse; preserve reached-prefix visibility and ordinary ordered composition between strokes |
| 3. Skip inactive paper samples before expensive distance/edge work | Python vector expressions currently evaluate complete patches | Compiled loops can test grain eligibility first; benchmark branching versus SIMD, and preserve exactly which samples contribute |
| 4. Reuse coordinate vectors; simplify scalar interpolation | Repeated `arange`, temporary vectors and general-purpose scalar `np.interp` calls | Reuse exact pixel-center coordinates in any implementation; small bounded opportunity relative to the deposition kernel |
| 5. Parallel tile or stroke-mask computation | Python coordination and runtime overhead complicate efficient CPU parallelism | Bound temporary buffers, retain stroke/layer compositing order; benchmark memory-bandwidth and scheduling limits |
| Later: swept-envelope or adaptive sampling algorithms | Not primarily a language issue | Can reduce redundant dab work, but changing the half-unit sample sequence can change pixels and reveal behavior; requires a separate fidelity decision |

Already accepted field caching, local stroke buffers and source-resolution composition should transfer to a Rust implementation. Porting alone does not remove overlapping dab work, memory traffic or source-resolution costs. Further parser, PNG writer, layer-compositor or cache-capacity tuning is not justified as the main next step for this page.

## Recommended Rust/WASM boundary

Prototype only the pencil deposition path first, using a contiguous batch of reached stroke samples and resident paper fields. Keep calls coarse-grained: a stroke or frame update, not one foreign-function call per dab. Reuse buffers for the distance/coverage/update loop, or fuse those operations directly. Keep the existing Python renderer and golden images as the reference. Native Rust and WASM should each be checked independently for rounding, transcendental-function and pixel equality; no cross-target equality is assumed.

Python acquisition, parsing and reference-comparison tools can remain in place because their measured costs are small. A browser adapter can load normalized page data once and submit small replay-state updates while retaining buffers inside the renderer. Browser transfer/presentation and scheduling costs were not measured in this local Python run and require their own prototype benchmark.

Start with an exact-output native kernel and measure unprofiled wall time, retained/peak memory, full birthday PNG equality and all 111 progressive golden frames. Then compile the same core to WASM and repeat correctness/performance checks there. Broad parallelization or a parser/UI rewrite is not a prerequisite for testing this boundary.

## Evidence

Private/generated evidence is ignored under `artifacts/profile-current-20260925/`: `birthday-profile.json`, `birthday.prof`, sorted text profiles, `stages.json`, and reproducible profiling scripts. The complete profiled PNG matches the accepted golden; production source hashes were unchanged throughout profiling. Earlier paired timings and golden replay frames remain under `artifacts/performance-20260925/`. These are one-machine observations, not universal throughput guarantees.


## Fused Rust prototype — 2026-09-25

The optional std-only Rust kernel now batches all reached dabs of a current-pencil stroke in one C ABI call. It fuses distance, boundary, threshold, rounding and max-union operations into a pixel loop. The host supplies NumPy-interpolated pressure occupancy and a NumPy-generated gain lookup table to preserve existing calibrated values. Python still owns sampling, stroke/layer composition, brush/calligraphy rendering and export. No profile was refitted.

Measured on this Windows x86-64 machine with Rust 1.88 release/LTO:

| Unprofiled workload | Python | Rust | Observed ratio |
|---|---:|---:|---:|
| Natural 24 strokes, cold |2.286s|0.688s|3.32×|
| Natural 24 strokes, warm |2.369s|0.672s|3.52×|
| Broad 4 strokes, cold |4.391s|2.415s|1.82×|
| Broad 4 strokes, warm |4.024s|2.426s|1.66×|
| Full birthday page 12, 702×936 output |261.531s|103.707s|2.52×|

The small samples were measured during this pass. The full Python timing is the earlier unprofiled optimized run, not a simultaneous paired rerun. These are individual machine observations, not statistical confidence intervals. “Warm” repeats the page in-process; Rust's bounded paper cache is recreated per stroke, unlike Python's shared tile cache. Full render time falls from about 4m22s to 1m44s; this is not real-time rendering.

Exact validation passed with no pixel tolerance: 600 dab-mask cases, 240 varied synthetic RGBA/PNG frames, all 14 control pages/585 cells, all 111 progressive golden frames, and the complete birthday drawing. Final replay frame equals static output. Birthday PNG SHA256 remains `c92bd8525f3496b638958b9051db9d558ae56a18e5a251eb67d5b5421f2be692`. The eight Rust tests, seven native-adapter tests and full 264-test Python suite pass. The short 111-frame public replay command took about 9.4s including encoding; it establishes integration/parity, not a demonstrated end-to-end replay speedup.

Python remains the default. Enable the prototype through `--pencil-backend rust` or `RenderOptions(pencil_backend="rust")`. See `native/pencil-kernel/README.md` for the offline build and explicit library override. Replay manifests record ABI1 and binary SHA256; validated DLL hash is `6288d1037359df8e3bada002ef8eb7ce6c645b051e0539df6dc4a2cd3582aead`. Private output and reproducible validation scripts are under ignored `artifacts/rust-prototype-20260925/`.

This confirms that batching/fusing the deposition boundary helps without a full application rewrite. Removed Python dispatch and NumPy temporary arrays are implementation-specific savings; avoiding redundant pixel work, preserving cache locality and batching are language-independent. Broad strokes improve less than narrow ones, so native arithmetic and repeated pixel visits still matter. The next investigations are profiling this native loop (including `hypot`, repeated threshold work and cache reuse), then compiling the same core for WASM with a browser harness. WASM was not built or benchmarked in this pass. Its host must reproduce the lookup/calibration inputs and independently prove numeric and output equivalence; native speedups cannot be assumed to transfer unchanged.
