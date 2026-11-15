# rm-redraw

Deterministic reMarkable ink rendering for native Rust and WebAssembly: normalized pages to RGBA, with textured pens, compositing, erasure and progressive stroke reveal. Part of [rePlay](https://github.com/domjancik/replay).

## Rust API

Install the renderer (the Rust library name remains `redraw`):

```toml
[dependencies]
redraw = { package = "rm-redraw", version = "0.1" }
```

```rust
use redraw::{model::{Page, Request, Options}, render::render};
let request = Request {
    page: Page {
        page_id: "example".into(), paper_size: Some([64.0, 64.0]),
        groups: vec![], strokes: vec![], compositing_order: vec![],
    },
    options: Options::default(), visibility: None,
};
let image = render(&request).expect("valid page");
assert_eq!(image.data.len(), image.width * image.height * 4);
```

`model::Request` supports serde JSON. `visibility: None` renders a static page; partial visibility reveals completed strokes plus an active stroke. The `render-json` binary reads a JSON request and writes raw RGBA, reporting dimensions on stdout.

## WebAssembly

```sh
cargo build --release --target wasm32-unknown-unknown
```

Output: `target/wasm32-unknown-unknown/release/redraw.wasm`. Use the included `renderer.mjs` wrapper. Existing `rm_renderer_*` C/WASM symbols remain unchanged for ABI version 1 compatibility.

This crate does not acquire or parse notebooks. Use the separate `rm-rmdoc` reader and normalize inputs first. Run untrusted work in a cancellable worker/process: input limits are not a CPU-time guarantee. Textures approximate native ink, not the proprietary renderer.

Requires Rust 1.88+. MIT project code and MIT-CMU Pillow-derived routines; both license texts are included. [Validation guide](https://github.com/domjancik/replay/blob/main/docs/rust-renderer.md).

[Try rePlay](https://replay.domj.net) · [Support development on Ko-fi](https://ko-fi.com/domjancik)

## Prepared replay sessions

The JavaScript wrapper offers `load(request)` followed by `frame(visibility)`.
`load` validates and retains the immutable page/options; `frame` sends only visibility.
Pass `null` for a final image. Loading another page replaces the session. Calling the
legacy `render(request)` also invalidates the prepared session. Invalid loads clear
it; invalid frames clear the raster cache. The added `rm_renderer_load_json` and
`rm_renderer_frame_json` exports extend ABI v1 without changing existing exports.

The cache stores occupied 64-pixel tiles and recomposites affected tiles in layer
order. Retained RGBA caches are capped at 64 MiB; dense inputs can fall back to the
stateless renderer. This cap excludes page data, transient raster buffers and WASM
allocator high-water memory. Coordinates and texture sampling remain unchanged.
## Experimental high-resolution grain

`options.high_res_grain: true` opts into curved grain cells for current pencil
and mechanical pencil, only when both composition scales are at least twice source resolution.
It defaults to false. Pressure knots, coarse density gain, boundary texture,
stroke geometry and layer composition are unchanged. Two area-preserving shears
warp the occupancy field, adding fine edge variation without increasing the
underlying noise frequency. Finite strokes and raster sampling can still change
ink mass slightly; this is an aesthetic departure, not additional native fidelity.
The option participates in cache identity and works with prepared replay sessions.
It can be slower. See `scripts/compare_high_res_grain.py` for pressure/angle/overlap
comparisons and optional private drawing crops. No new app-export calibration is claimed.
