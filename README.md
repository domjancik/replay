# rePlay

Turn reMarkable notebooks into drawing animations. Select pages, choose layer or entry order, crop the drawing, and export a replay or a forward/reverse loop.

**[Open rePlay](https://replay.domj.net/app)** · [About and examples](https://replay.domj.net) · [Creator](https://domj.net) · **[Support development on Ko-fi](https://ko-fi.com/domjancik)**

The hosted app parses notebooks and renders ink on your device with Rust compiled to WebAssembly. No Python or CLI installation is required. Import a `.rmdoc` or connect reMarkable Cloud through a stateless relay. Saved pairing information stays in your browser. USB import uses an optional [desktop companion](docs/usb-companion.md).

## Repository map

| Component | Location | Responsibility |
| --- | --- | --- |
| Hosted app | [native/hosted](native/hosted) | Workers, cloud relay, browser storage and deployment build |
| Shared UI | [src/rm_redraw/web/static](src/rm_redraw/web/static) | Production gallery, queue, controls and styles |
| **rm-redraw** | [native/redraw](native/redraw) | Standalone Rust/WASM ink renderer: normalized pages to RGBA |
| rm-rmdoc | [native/rmdoc](native/rmdoc) | Archive reader, v5/v6 parser and normalization |
| Replay core | [native/replay-core](native/replay-core) | Scheduling and anchor matching |
| Python tools | [src/rm_redraw](src/rm_redraw) | USB companion, acquisition, calibration oracle and legacy local app |
| Documentation | [docs](docs/README.md) | Guides, architecture and calibration history |

## Limits

Replay timing and entry order are inferred, not recovered wall-clock history. Ink textures approximate native rendering. Typed text, templates and PDF/EPUB backgrounds are outside the ink renderer. Some anchored pages require matching native export evidence. App PNG and tablet PDF are distinct calibration paths.

## Development

See the [development guide](docs/development.md), [renderer validation](docs/rust-renderer.md), and [Python deprecation status](docs/python-status.md). The production runtime is Rust/WASM; Python remains a differential reference and development tool.

```sh
cargo test --locked --manifest-path native/redraw/Cargo.toml
cargo test --locked --manifest-path native/rmdoc/Cargo.toml
node --test tests/web/*.test.mjs tests/hosted/*.test.mjs
```

The older local utility remains available through [installation instructions](docs/install.md).

## License and support

Project code is MIT licensed. Pillow-derived renderer routines also carry MIT-CMU terms; see [third-party notices](THIRD_PARTY_NOTICES.md). Private captures and rendered artwork are not included.

[Support rePlay on Ko-fi](https://ko-fi.com/domjancik) · [Report an issue](https://github.com/domjancik/replay/issues)

## Rust crates

- [rm-redraw](https://crates.io/crates/rm-redraw): native and WASM ink rendering (Rust library name `redraw`).
- [rm-rmdoc](https://crates.io/crates/rm-rmdoc): notebook archive reading, page parsing and normalization.
- [rm-replay-core](https://crates.io/crates/rm-replay-core): replay scheduling and anchor fitting.

The initial releases are version 0.1.0; APIs are experimental. Each crate includes its license and usage documentation.
