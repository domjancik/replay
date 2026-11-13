# Browser replay feasibility

The current pencil and mechanical-pencil deposition kernel can run on the user's device as WebAssembly. On this Windows machine, the same Rust source produced six synthetic alpha masks byte-identical to Python/NumPy and native Rust. This covers the pixel-deposition step after pressure calibration and dab generation. The browser parser, replay renderer, compositor, and video exporter still need end-to-end validation.

## Measured prototype

Rust 1.88.0 built the unchanged kernel for `wasm32-unknown-unknown` offline. The raw kernel module is 27,456 bytes. The 21,168-byte runnable wrapper exposes aligned buffer allocation and the existing draw ABI, and has zero WASM host imports. The JavaScript adapter uses standard WebAssembly and typed-array APIs. Node v26.4.0 on an AMD Ryzen 9 8945H ran the test. [Rust target support](https://doc.rust-lang.org/rustc/platform-support/wasm32-unknown-unknown.html)

| Synthetic mask | Dabs | Mask bytes | One Node draw call |
| --- | ---: | ---: | ---: |
| Center pixel | 1 | 1 | 1.0 ms |
| Zero pressure with an existing mask value | 1 | 1 | 0.2 ms |
| Negative origin and unequal scales | 3 | 63 | 0.2 ms |
| Overlap, clipping, and tile boundaries | 90 | 26,123 | 4.2 ms |
| Broad pencil at unequal scales | 400 | 98,304 | 72.6 ms |
| Larger viewport with narrow pencil | 1,200 | 657,072 | 13.8 ms |

Each case uses the exact NumPy-produced float64 occupancy and 65,536-entry gain table bytes. The runner also checks empty and invalid-scale batches. The timings are exploratory observations of one pass and include JS-to-WASM transfer and result copy. Linear memory reached 5.5 MiB across the cases. Rendering a complete frame would additionally require stroke sampling, tool rasterization, layer composition, downsampling, and output. The prototype uses synthetic input and leaves browser and mobile throughput unmeasured.

## Route to a client-side animator

Test the existing Python parser, scheduler, and renderer in a Pyodide worker before committing to a full port. The CPython 3.13-based Pyodide 0.29 series publishes compatible-range NumPy and Pillow builds, and `rmscene==0.8.0` has a universal wheel. Its `packaging>=23,<24` dependency needs explicit resolution because the published Pyodide 0.29.2 package list has `packaging==24.2`. The current Pyodide 314 series uses Python 3.14, outside this project's declared range. Start by exercising the Python pencil path, then consider calling the measured Rust WASM kernel through the worker's JS bridge in place of the native DLL adapter. Desktop FFmpeg and Poppler subprocesses require separate browser replacements or exclusion from the initial input scope. Measure cold download, Python/JS/WASM copies, peak memory, full-frame parity, and render speed before deciding how much to port. This option has package-level evidence and awaits an actual engine run. [Pyodide package list](https://pyodide.org/en/0.29.2/usage/packages-in-pyodide.html), [Pyodide release notes](https://pyodide.org/en/stable/project/changelog.html), [Pyodide workers](https://pyodide.org/en/0.29.2/usage/webworker.html), [rmscene wheel](https://pypi.org/project/rmscene/0.8.0/), [Python subprocess availability](https://docs.python.org/3.13/library/subprocess.html)

If startup or throughput calls for a dedicated Rust and TypeScript implementation, the normalized contracts support an incremental port.

| Stage | Existing implementation | Work to run locally in a browser |
| --- | --- | --- |
| Acquire raw pages | Local file and USB/SSH providers | Start with local `.rmdoc` or `.rm` import. Add cloud access behind a distinct read-only provider after pairing and page-download behavior are verified. |
| Parse and normalize | Python `rmscene` adapter, geometry resolution and `pipeline.py` | Feed one versioned render projection to the worker during renderer development. For raw browser import, run the existing parser in a compatible browser runtime or port and compare against its fixtures. Preserve raw channels, CRDT IDs, tombstones, unknown diagnostics, layer visibility, affine evidence and separate orderings. Anchored documents that require paired native PDF evidence need a supported path or a clear unresolved state. |
| Schedule replay | `replay/schedule.py` and render-geometry helpers | Transfer the small deterministic scheduling logic and fixed-distance reveal. Preserve duration and hold behavior, layer/entry ordering and the distinction between inferred replay order and compositing order. |
| Rasterize strokes | `rendering/texture.py`, `brush.py`, `simple.py`, `calligraphy.py`, `pillow.py` | Port exact pencil sample generation, bounds, pressure interpolation and a pinned little-endian 512 KiB gain table. Port current brush and legacy textures, ordinary pens including ballpoint, highlighter Darken, calligraphy, and layer-local erasers. |
| Compose and present | `PillowRenderer` | Keep the normalized page and canvas state resident in a dedicated worker. Port fixed viewports, source-over and erasing, prefix-cache behavior including non-prefix fallback, global grain phase and the final BOX reduction. Canvas can present the finished raster. Prove its rounding and resampling against the Python reference before using it for those calculations. |
| Encode and download | PNG sequence and local FFmpeg H.264 | Use WebCodecs where the actual codec, dimensions and rate pass `VideoEncoder.isConfigSupported()`. Mux encoded chunks and their decoder configuration into MP4 for H.264 or WebM for a supported WebM codec. Keep fixed timestamps and apply queue backpressure during offline export so every scheduled frame survives. |

Load a page once and send compact replay options and progress updates to the worker. The prototype allocates and copies mask, samples and gains per call. A renderer should retain the gains and reuse aligned stroke buffers inside WASM, reacquiring typed views after memory growth. At 1404×1872, one RGBA surface is 10.0 MiB, four simultaneous surfaces are about 40 MiB, and a page-spanning 4× pencil mask could add about 40 MiB on its own. Retain clipped stroke bounds and release active layers and frame resources promptly. Buffering ten seconds of raw 1080p RGBA at 30 fps would consume about 2.3 GiB. Stream frames through encoding, close each submitted `VideoFrame`, and stream muxed output to a file sink when available. Probe actual memory and output storage on the target mobile browsers before setting supported dimensions. [WebAssembly memory API](https://webassembly.github.io/spec/js-api/#memories), [WebCodecs](https://www.w3.org/TR/webcodecs/), [Chrome WebCodecs examples](https://developer.chrome.com/docs/web-platform/best-practices/webcodecs), [File System Standard](https://fs.spec.whatwg.org/)

Cloud pairing has its own feasibility gate. Direct browser requests require the selected API to allow the app origin, preflight, authentication headers and any credentials used by the flow. A read-only connector may be needed if the supported API or its cross-origin rules prevent direct access. Client-side rendering and encoding can remove per-job server compute and video storage. Hosting and any required connector still have traffic and operational costs. [Fetch CORS protocol](https://fetch.spec.whatwg.org/#http-cors-protocol)

The next experiment is a local browser-worker pipeline using a page with layered ordinary ink, current pencil, brush and an eraser. Compare complete RGBA frames against Python, verify the worker's last forward frame equals its static output byte for byte, and play the resulting muxed video. Run the same measurement on desktop Chromium and a representative mobile browser, including elapsed time, peak memory, and cancellation. Evaluate cloud acquisition against the same normalized contract.

## Reproduce

Run from the repository root using PowerShell, the project Python environment, Rust with the WASM target installed, and Node. Generated inputs, masks and binaries are written under the ignored `artifacts/wasm-feasibility-20261113/` directory.

```powershell
$probeTarget = "artifacts/wasm-feasibility-20261113/target"
cargo build --locked --offline --release --manifest-path native/pencil-kernel/Cargo.toml --target-dir $probeTarget
cargo build --locked --offline --release --manifest-path native/pencil-kernel/Cargo.toml --target wasm32-unknown-unknown --target-dir $probeTarget
cargo build --locked --offline --release --manifest-path native/wasm-prototype/Cargo.toml --target wasm32-unknown-unknown --target-dir $probeTarget
$env:RM_REDRAW_PENCIL_LIBRARY = (Resolve-Path "$probeTarget/release/rm_pencil_kernel.dll").Path
.venv/Scripts/python.exe native/wasm-prototype/make_goldens.py
node --test native/wasm-prototype/pencil.test.mjs
```

The native kernel's eight ABI tests and 204 Python rendering and replay tests passed with the freshly built native DLL. There were no device or cloud requests.
