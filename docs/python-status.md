# Python and prototype status

The hosted app uses Rust/WASM for archive reading, parsing, normalization and rendering. Python and Pyodide are not browser runtime requirements.

## Deprecated

Do not build new product features on `native/browser-prototype` (Pyodide renderer), `native/wasm-prototype` (pencil-only WASM), or `native/pencil-kernel` (Python pencil acceleration). They remain for historical experiments and reproducibility. Use `native/rmdoc`, `native/redraw` and `native/hosted` instead.

The Python local web utility is a legacy alternative, not the primary distribution. Python parsing/rendering APIs remain calibration and differential references; new production format/rendering work belongs in Rust. `native/hosted/bridge.py` is a test/reference bridge, not deployed browser code.

## Still active

- `src/rm_redraw/companion`: optional USB desktop companion.
- Acquisition, comparison and fixture scripts: capture and native-reference calibration.
- Python parser/renderer and golden generators: differential oracle.
- `native/hosted/build.py`: hosted staging and configuration generation.
- `src/rm_redraw/web/static`: production JavaScript/CSS/HTML despite its Python package location.
- `native/video-prototype`: encoder build consumed by hosted staging; not retired.

No raw fixtures or oracle code were deleted. Removing active Python utilities requires replacing their separate responsibilities first.
