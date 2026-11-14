# WASM replay performance pass — 2026-11-14

## Scope and measurement

These are Windows desktop Node 26.4.0 WASM measurements, not phone speed claims.
Three fresh renderer instances per synthetic workload; table shows the median.
Each workload produces 80 frames. Timings include frame hashing, serialization,
raster work, compositing and copies, but not video encoding. Baseline WASM was
saved before this pass. Raw reports and the natural-drawing input stay ignored
under `artifacts/mobile-performance/`.

| Workload | Before | After | Ratio | WASM memory before → after |
|---|---:|---:|---:|---:|
| Detailed page, 13,000 points, 192px | 453 ms | 80 ms | 5.64× | 5.3 → 4.3 MiB |
| Textured pencil, 384px | 315 ms | 317 ms | 0.99× (effectively unchanged) | 4.9 → 7.3 MiB |
| 26 layers, 768px | 1300 ms | 277 ms | 4.69× | 70.5 → 26.6 MiB |

Every frame's combined SHA-256 agrees with the baseline. An additional natural
120-stroke prefix at 702×936, six frames, took 1278 → 1177 ms (one sample, 1.09×),
with matching frame hashes and static/final equality; WASM memory was 92.9 →
57.4 MiB. This is a prefix, not a full drawing benchmark. A full 12-frame natural
run was stopped before producing a result. No full-natural-replay speedup is claimed.
WASM memory is allocated linear-memory high-water size, not total browser memory.

## Shipped changes

- Additive prepared-page ABI: upload and validate page/options once; send only
  frame visibility. Existing JSON render API and ABI version 1 remain supported.
- Sparse 64×64 layer-prefix tiles replace full-canvas buffers for every layer.
  Empty layers no longer trigger the 64 MiB cache cliff. Affected tiles are
  recomposited in original layer order; drawing coordinates and texture phase
  are unchanged. Retained RGBA buffers have a 64 MiB budget; dense overflow can
  still use the stateless fallback. Transient allocations are additional.
- Progress previews are PNG-encoded at maximum 384px side, no more frequently
  than once per 1.5 seconds of processing. Final downloads retain full resolution.
- Reverse-loop frames are reused from a 16 MiB bounded cache, restricted to the
  frames actually needed by the loop. Uncached frames render normally. Cropping
  is performed once per produced frame.
- Run manifests include static, frame/rotation/crop and preview times, total time
  and reverse-cache hits. Total includes encoding; individual timers are not a
  claim to measure encoder hardware time independently.

## Parallelism experiment

Two independent workers render contiguous halves, maintaining each worker's
prefix cache. Startup, page transfer, worker instantiation and duplicated prefix
work are included. All frame hashes equal serial output.

| Workload | Serial median | Two-worker median | WASM memory serial / combined |
|---|---:|---:|---:|
| Detailed page | 88 ms | 113 ms | 4.3 / 8.8 MiB |
| Textured pencil | 352 ms | 262 ms | 7.3 / 13.8 MiB |
| Many layers | 326 ms | 282 ms | 26.6 / 45.6 MiB |

Keep production single-worker for now: gains are workload-dependent and memory
increases materially. Desktop results do not establish thermal or memory safety
on phones. `/benchmark.html` runs this one-versus-two-worker experiment on the
actual device using synthetic pages; results remain local. This is a diagnostic,
not an automatic rendering-quality change. Shared-memory/tile-worker production
parallelism is deferred pending those device measurements.

## Validation and reproduction

- Native Rust tests and Rust 1.88 compatibility check.
- 114 synthetic WASM golden cases exact (zero changed channels).
- Worker integration compares every rotated/cropped forward and reverse frame
  against the renderer; verifies one page upload and no reverse rerenders when
  needed frames fit the cache.
- Existing web/hosted suites, plus bounded reverse-cache and sparse-layer tests.

```powershell
cargo test --locked --offline --manifest-path native/redraw/Cargo.toml
cargo build --locked --offline --release --target wasm32-unknown-unknown --manifest-path native/redraw/Cargo.toml
node native/redraw/benchmark-mobile.mjs artifacts/mobile-performance/current.json
node native/redraw/benchmark-parallel.mjs
node native/redraw/verify.mjs --wasm native/redraw/target/wasm32-unknown-unknown/release/redraw.wasm --suite synthetic
node --test tests/web/*.test.mjs tests/hosted/*.test.mjs
```

The benchmark scripts require an existing `artifacts/mobile-performance` directory.
Repeated measurements on the same device are preferable to comparing different
browser/phone models or extrapolating from logical-core counts.
