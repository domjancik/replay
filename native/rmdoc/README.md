# rm-rmdoc

Independent Rust reader for reMarkable `.rmdoc` archives and v5/v6 `.rm` pages. It preserves source channels, IDs, group transforms, metadata and unknown records, and projects normalized data for a renderer without depending on one. Native and standalone WASM use the same implementation. No Python, filesystem extraction, tablet connection or cloud client is required by the library.

This is an experimental 0.1 API. Unknown future formats are rejected explicitly; see the format-update policy below.

```toml
[dependencies]
rm-rmdoc = "0.1"
```

```rust,no_run
use rm_rmdoc::{archive, normalize};

# fn example() -> Result<(), Box<dyn std::error::Error>> {
let bytes = std::fs::read("notebook.rmdoc")?;
let notebook = archive::inspect(&bytes)?;
let first = &notebook["pages"][0];
let raw = archive::page_bytes(&bytes, first["member"].as_str().unwrap())?;
let parsed = normalize::parse(&raw, first["id"].as_str().unwrap(), &rm_rmdoc::Value::Null)?;
// Supply evidenced geometry; these example dimensions are not device detection.
let drawing = normalize::project(&parsed, [1404., 1872.], [1., 0., 0., 1., 702., 0.])?;
# Ok(()) }
```

`parse_with_strategy` also accepts `scene-order`; the default `crdt-order` is inferred, never verified chronology. `archive::metadata` preserves full content and metadata JSON. Parsed JSON follows the repository's normalized-page contract, while diagnostics use Rust-specific framing and retain raw unknown bytes. Projection requires usable geometry; browser preparation additionally rejects unresolved anchors and unacknowledged clipping. A supplied anchor layout is `{offsets: {"author:counter": y}, evidence: "..."}`.

## Browser ABI

`reader.mjs` exposes `instantiateReader(wasmBytes).execute(rawBytes, options)`. Operations are `inspect`, `info`, `parse`, `project`, `anchors` and `prepare`. For page operations specify `page`, optionally `member` when raw bytes are a notebook archive. `project` takes `paper_size` and `source_affine`; `prepare` takes hosted replay `settings`. Timing and rendering remain separate crates.

The owned-buffer ABI is version 1. Input bytes are separate from JSON arguments, avoiding base64 or byte-array inflation. Limits are 128 MiB input, 4 MiB arguments and 128 MiB serialized output. Copy returned data before the next call and free owned input buffers. Hosts must isolate untrusted parsing in a cancellable worker; input limits are not a strict peak-memory or CPU-time guarantee.

Archives are bounded to 20,000 entries and 512 MiB expanded data. Unsafe paths, duplicate names, encryption, CRC errors, ZIP64 directories and multidisk archives reject explicitly. Page parsing bounds block/point/text counts and group depth. Unknown file major versions reject; unknown block payloads remain diagnostic data. Projection rejects unreadable or unsupported potentially geometric blocks, which is deliberately stricter than the Python reference's permissive diagnostic path.

## Build and verify

```powershell
cargo test --manifest-path native/rmdoc/Cargo.toml --offline
cargo build --manifest-path native/rmdoc/Cargo.toml --target wasm32-unknown-unknown --release --offline
.venv/Scripts/python.exe native/rmdoc/generate_cases.py
node native/rmdoc/verify.mjs
node native/rmdoc/verify_pixels.mjs
node --test tests/hosted/reader.test.mjs
```

For exact decoded-block checks, run `native/rmdoc/tests/generate_v6.py`, set `RMDOC_V6_DIFFERENTIAL` to the absolute generated `artifacts/rmdoc-v6/cases.json` path, and run `cargo test --manifest-path native/rmdoc/Cargo.toml --test v6 -- --include-ignored`.

Python is a development oracle only. `generate_corpus.py --archive PATH --out artifacts/PRIVATE-DIR` enables explicitly selected saved-corpus validation; never commit its outputs. `verify.mjs DIR` compares the generated cases through the actual WASM ABI. Semantic parity excludes diagnostic framing and explanatory prose, not geometry, channels, IDs, visibility or order. Unknown-geometry rejection is checked explicitly.

See [FORMAT_UPDATES.md](FORMAT_UPDATES.md) for the version-update and release process. The v6 format translation retains upstream rmscene's MIT notice in `LICENSE-RMSCENE`. Tool calibration and pixel fidelity are properties of the separate renderer, not claims of this parser crate.

`NORMALIZATION_SCHEMA_VERSION` identifies the normalized JSON contract; `rm_doc_abi_version` independently identifies the buffer ABI. Neither is the input file-format version.

[Try rePlay](https://replay.domj.net) · [Support development](https://ko-fi.com/domjancik)
