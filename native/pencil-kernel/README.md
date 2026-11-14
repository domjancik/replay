> **Deprecated prototype.** Use the full Rust/WASM reader and renderer for new work. See [Python and prototype status](../../docs/python-status.md). Retained for research reproducibility.

# Optional pencil kernel

This dependency-free Rust crate implements the current app-PNG pencil coverage kernel. The Python renderer still owns stroke sampling, pressure calibration, compositing and output. Its default remains Python.

Build from the repository root with Rust 1.88 or later and the platform linker:

```powershell
cargo build --release --offline --manifest-path native/pencil-kernel/Cargo.toml --target-dir artifacts/rust-kernel-build
cargo test --offline --manifest-path native/pencil-kernel/Cargo.toml --target-dir artifacts/rust-kernel-build
.venv/Scripts/python.exe -m pytest tests/rendering/test_native_pencil.py -q
```

On Windows the adapter discovers `artifacts/rust-kernel-build/release/rm_pencil_kernel.dll`. Use `RM_REDRAW_PENCIL_LIBRARY` for an explicit library path. Other platforms need their corresponding shared-library path and independent equivalence validation.

Add `--pencil-backend rust` to the existing replay command, or construct `RenderOptions(pencil_backend="rust")`. The older `pencil_boundary` profile is unsupported. Missing or incompatible libraries raise an error; there is no silent fallback. Restart Python after rebuilding a loaded library.

`rm_pencil_draw` accepts a contiguous writable uint8 mask, dimensions and integer global origin, positive float64 scales, opacity, consecutive float64 `[x, y, radius, occupancy]` rows and a 65,536-entry gain table. Radius uses the existing 0.70-profile convention; occupancy and gain values come from the host reference arithmetic. Status codes and pointer safety requirements are documented in `src/lib.rs`. Safe Rust callers can use the slice-based `render` function. Paper fields are retained only within one call, bounded to 6 MiB plus one incoming tile and small coordinate/metadata storage.

The core uses no Python APIs or OS services. WASM compilation, its host bindings, numeric equivalence and browser performance have not yet been validated. In particular, the browser must reproduce pressure interpolation and gain values, and test its math/rounding against the reference before promotion.

See `docs/calibration-journey.md` in the repository for measured performance and validation scope. Build output and private reference artifacts must remain ignored.
