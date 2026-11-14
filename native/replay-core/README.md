# Native replay core

Dependency-light Rust implementations of native-reference anchor fitting and duration scheduling, usable as a native Rust library or standalone WASM. PDF interpretation remains in browser PDF.js; notebook parsing/normalization remains in Python/Pyodide. This crate does not acquire documents or render ink.

Build and verify from the repository root:

```powershell
cargo test --manifest-path native/replay-core/Cargo.toml --offline
cargo build --manifest-path native/replay-core/Cargo.toml --target wasm32-unknown-unknown --release --offline
.venv/Scripts/python.exe native/replay-core/generate_cases.py
node native/replay-core/verify.mjs
```

`core.mjs` wraps the owned-buffer ABI, version 1. `match(request)` accepts either `op: "anchors"` (the default) or `op: "schedule"` and returns decoded JSON. Inputs and outputs are bounded to 32 MiB. Callers must use the allocator and release allocations; output pointers remain valid until the next invocation. No WASI or external imports are required.

Anchor requests contain a binary ink mask, width/height, and direct-stroke templates with expected X translations. Exact Euclidean distance transforms feed bounded translation search, quarter-pixel refinement, reverse overlap and ambiguity checks. Rejected evidence stays rejected; the caller separately checks shared-anchor agreement and records PDF provenance. Limits include 12 million mask pixels, 8192 pixels per axis, and a search work budget.

Schedule requests contain a normalized renderer page, FPS, duration and `entry` or `layer` ordering. Returned visibility states preserve compositing independence and include a one-second final hold. Scheduling does not infer timestamps. Memory bounds may reject exceptionally large schedules.

Differential fixtures are synthetic and generated under ignored `artifacts/`. They compare accepted/rejected anchor outcomes and candidate metrics with Python, and entire visibility schedules with the Python implementation. Private native-export evidence is never included in this crate.
