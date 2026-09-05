# Repository agent instructions

Read the project brief, `plans/kickoff-readiness.md`, and `docs/contracts.md` before editing.

- Use test-driven development for behavior: add a focused failing test, observe the expected failure, implement, and rerun the full relevant suite.
- Existing tablet documents are read-only. Never stop or restart xochitl. Never write to the tablet unless a later task explicitly authorizes a dedicated fixture write.
- Only the acquisition owner may connect to `10.11.99.1` or the USB API during the initial parallel phase.
- Never commit SSH credentials, device-derived raw files, `.rmdoc` archives, native private PDFs, rendered output, or videos.
- The coordinator owns root configuration, shared contracts, and integration. Workers must not edit `pyproject.toml`, `uv.lock`, `.python-version`, `.gitignore`, `AGENTS.md`, or `docs/contracts.md` without coordinator approval.
- Keep acquisition, parsing, replay timing, rendering, and comparison separate. The parser must not import a renderer; the replay engine must depend on a renderer interface rather than a concrete backend.
- Preserve unknown format data in diagnostic form. Keep compositing order and replay order distinct and label inferred order honestly.
- Use fixed viewports. The final replay frame must be byte-identical to static output from the same backend and options.
- Put generated or private artifacts only under ignored paths. Do not modify raw snapshots.

Initial exclusive source ownership:

- Acquisition: `src/rm_redraw/acquisition/`, `tests/acquisition/`
- Parser/normalization: `src/rm_redraw/parsing/`, `tests/parsing/`
- Replay/render/video: `src/rm_redraw/replay/`, `src/rm_redraw/rendering/`, `tests/replay/`, `tests/rendering/`
- Coordinator: shared/root files and cross-module integration

