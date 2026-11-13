# Rust and WebAssembly ink renderer

The Rust renderer consumes normalized page coordinates, render options and a visibility state. The same crate builds a native executable and a WebAssembly module. The browser worker uses the WASM module directly. Python remains the differential reference and supplies the synthetic probe's prepared requests. Raw notebook parsing, anchor resolution and replay scheduling occur before this renderer boundary.

## Renderer contract

Each JSON request contains `page`, `options` and `visibility`. `page` uses the render projection produced by `rm_redraw.pipeline.to_render_page`. It carries source dimensions, groups, ordered strokes, tool identities, resolved RGBA colors and raw point channels. `options` contains the optional fixed viewport, background RGBA and sparse pencil-boundary flag. `visibility` is either `null` for the static image or a set of completed IDs plus an optional active stroke and progress fraction. Rendering follows compositing order even when a replay reveals strokes in a different sequence. The current request API sends and parses the complete page for each frame. A retained-page API and cache would need separate parity and performance checks before use on long browser replays.

The WASM ABI version is 1. JavaScript copies UTF-8 JSON into an allocated input buffer and frees the input after rendering. The renderer exposes dimensions, RGBA bytes or a diagnostic through pointer/length pairs. The wrapper copies pixels after rendering because WebAssembly memory may grow and the next render may reuse the output. Native ABI callers must allocate, write, render, read and free on the same thread. Finish writing the input before the render call and copy the result before the next render. The native executable takes an input JSON path and output RGBA path and emits dimensions on stdout. No platform graphics library or Python runtime is needed to call the compiled WASM renderer.

The request and geometry limits reject oversized inputs. Accepted renders can still take substantial CPU time and allocate additional intermediate buffers. Run large or untrusted requests in a terminable worker or process with an external time limit.

## Reproduce the differential corpus

Run from the repository root in PowerShell. The checks use the project's Python environment, Rust 1.88 or later with the `wasm32-unknown-unknown` target, and Node. Generated data and compiled binaries go under ignored `artifacts/rust-renderer/`.

```powershell
$rustRendererTarget = 'artifacts/rust-renderer/target'
$env:PYTHONPATH = 'src'
.venv/Scripts/python.exe native/renderer/generate_goldens.py
cargo test --locked --manifest-path native/renderer/Cargo.toml --target-dir $rustRendererTarget
cargo build --locked --release --manifest-path native/renderer/Cargo.toml --target-dir $rustRendererTarget
cargo build --locked --release --target wasm32-unknown-unknown --manifest-path native/renderer/Cargo.toml --target-dir $rustRendererTarget
node --test native/renderer/renderer.test.mjs
node native/renderer/verify.mjs --native "$rustRendererTarget/release/render-json.exe" --wasm "$rustRendererTarget/wasm32-unknown-unknown/release/rm_renderer.wasm"
.venv/Scripts/python.exe native/renderer/tests/raster_differential.py "$rustRendererTarget/release/rm_renderer.dll"
node native/renderer/tests/raster_differential.mjs "$rustRendererTarget/wasm32-unknown-unknown/release/rm_renderer.wasm"
```

The corpus contains 114 synthetic cases. It covers all tool codes in the project's `rmscene` pen enum and the existing generic fallback, each at source size and in an anisotropic partial reveal. The corpus also exercises missing width, single and coincident points, fractional and off-canvas points, explicit alpha, translucent backgrounds, layer-local erasure, same-layer highlighter Darken, hidden layers, the two pencil boundary modes, source-resolution BOX, nonprefix visibility and a 29-frame entry-order replay plus static output. The verifier checks SHA-256 for each input golden, tests dimensions and reports changed pixels, maximum channel error, per-channel MAE and the first changed pixel. Any differing byte or render error makes the run fail. Pencil deposit and whole-page output are different checks. Python parity measures compatibility with the existing renderer and its experimental profiles.

The integrated November 13 synthetic run matched all 114 cases byte for byte in native Rust, in WASM through Node, and across the two Rust targets. The report is written under `artifacts/rust-renderer/verification/synthetic/`. The native verifier starts a separate executable for each case, while the WASM verifier reuses one module instance. Their per-case wall-clock times include different host overhead. The report records both tested binary hashes.

The two raster differential commands separately generate and verify 700 seeded nontexture cases covering eraser, ballpoint, marker, fineliner, highlighter, calligraphy and fallback rendering. Native and WASM matched every reference exactly, including clipping, missing channels, variable widths and partial reveals.

Optional private validation projects one selected saved archive member into the same contract. Supply `--natural-archive` and `--natural-member` to the generator for the previously measured 1404×1872 source canvas, +702 X translation and 702×936 output. Run `verify.mjs --suite private` with the desired backend flags. The private suite stays in a separate ignored directory and the browser harness exposes only generated synthetic cases.

The private validation rendered a 2,655-stroke, five-layer portrait. The current Python renderer regenerated the reference from the saved raw page and matched its frozen predecessor. Native Rust and WASM through Node both matched that reference byte for byte at 702×936. This is one natural static case, and the concurrent local runs were not a controlled timing comparison.

## Browser probe

Run `node native/renderer/browser/serve.mjs 8769` after generating the synthetic cases and building WASM. Open `http://127.0.0.1:8769`. **Render sample** exercises the Rust module and compares the replay and static RGBA with the Python corpus. **Render and encode** additionally streams the generated frames into the pinned local WebCodecs probe. Build that probe first for video. The harness reads the already scheduled normalized replay requests. [Local video probe](../native/video-prototype/README.md)

The November 13 browser run matched all 29 forward frames and the independent static image. The last forward frame matched static output. `ffprobe` reported 29 H.264 frames in the downloaded 72×54 MP4 at 12 fps. The harness reported 555 ms from the start of rendering through export and static comparison, including local fixture fetches after module load. This was one synthetic run.

## Puhu compatibility check

Puhu 0.4.1 is MIT-licensed and can handle many Python image-processing operations. Its tagged Rust crate is a `cdylib` with unconditional PyO3 0.24 extension-module and ABI3 features. Its manifest offers no independent Rust library target or Python-free WASM feature. The implementation wraps `image` 0.25.x operations for formats and scaling. [Pinned Cargo manifest](https://github.com/bgunebakan/puhu/blob/5d7a73ec5433dd7e0a31e9016de2bfcea95d40f6/Cargo.toml) · [Pinned module entry](https://github.com/bgunebakan/puhu/blob/5d7a73ec5433dd7e0a31e9016de2bfcea95d40f6/src/lib.rs) · [Puhu 0.4.1 distribution](https://pypi.org/project/puhu/0.4.1/)

The Windows wheel ran in an isolated target directory on Python 3.13.15 alongside Pillow 12.3.0. The tested wheel exposes no `ImageDraw`, `ImageChops`, `Image.alpha_composite`, `Image.frombytes` or Pillow-named `Image.tobytes`. Its `to_bytes` method can read raw bytes. BOX is unsupported. Lanczos reduction of a translucent 6×2 RGBA pattern to 3×1 differed on all three output pixels. Its unmasked `paste` uses source-over through `imageops::overlay`, with a one-unit red-channel difference on both pixels in the tested two-pixel translucent composition. These operations are part of renderer parity. Puhu remains a candidate for separate image I/O or processing workloads where those differences are acceptable. [Pinned image operations](https://github.com/bgunebakan/puhu/blob/5d7a73ec5433dd7e0a31e9016de2bfcea95d40f6/src/image.rs)

## Rust imaging libraries

The renderer needs raw image buffers and specific scan conversion, alpha, channel and resampling rules. Published APIs establish where existing libraries could help. Each changed primitive would still need to pass the pixel corpus.

| Library | Relevant operations and constraints |
| --- | --- |
| `image` 0.25.10 | MIT or Apache-2.0. Rust 1.88. Provides buffers and opt-in image codecs, which could be used at a future export boundary. Its resize filter enum includes Lanczos3 and omits BOX. Puhu's tested Lanczos and composition use this family of image operations and differ from Pillow. The standalone `image` version was assessed from source. [Cargo manifest](https://docs.rs/crate/image/0.25.10/source/Cargo.toml.orig) · [Resize filters](https://docs.rs/image/0.25.10/image/imageops/enum.FilterType.html) |
| `imageproc` 0.27.0 | MIT. Rust 1.87. Drawing exposes integer polygon points and caller-defined edge interpolation. Its antialiased polygon function uses antialiased line drawing for edges. The renderer depends on Pillow's polygon pixel inclusion followed by separately defined 4× mask reduction on several tools. WASM has a `getrandom` JavaScript backend in the manifest and the default features also bring in Rayon, image codecs, text and FFT. Direct primitive and browser bundle equivalence remain untested. [Cargo manifest](https://docs.rs/crate/imageproc/0.27.0/source/Cargo.toml.orig) · [Polygon implementation](https://docs.rs/imageproc/0.27.0/src/imageproc/drawing/polygon.rs.html) |
| `fast_image_resize` 6.1.0 | MIT or Apache-2.0. Rust 1.87. Provides BOX and Lanczos3, alpha-aware RGBA resizing and WASM SIMD paths. It is the closest candidate for a narrow future optimization. Before adopting it, compare grayscale masks and straight RGBA through the same alpha conversion, separable filtering, rounding and noninteger scale cases on both native and WASM. Its general resize documentation does not establish that output is identical to Pillow. [Cargo manifest](https://docs.rs/crate/fast_image_resize/6.1.0/source/Cargo.toml.orig) · [Filters](https://docs.rs/fast_image_resize/6.1.0/fast_image_resize/enum.FilterType.html) · [Alpha configuration](https://docs.rs/fast_image_resize/6.1.0/fast_image_resize/struct.ResizeOptions.html) · [WASM support](https://github.com/Cykooz/fast_image_resize) |
