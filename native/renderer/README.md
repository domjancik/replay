# redraw

Deterministic reMarkable ink rendering for native Rust and WebAssembly: normalized pages to RGBA, with textured pens, compositing, erasure and progressive stroke reveal. Part of [rePlay](https://github.com/domjancik/replay).

## Rust API

Before registry publication, use a checkout path dependency:

```toml
[dependencies]
redraw = { path = "../replay/native/renderer" }
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
