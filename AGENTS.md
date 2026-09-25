# Repository agent instructions

Read the project brief, `plans/kickoff-readiness.md`, `plans/milestone-acceptance.md`, and `docs/contracts.md` before editing.

- Use test-driven development for behavior: add a focused failing test, observe the expected failure, implement, and rerun the full relevant suite.
- Existing tablet documents are read-only. Never stop or restart xochitl. Never write to the tablet unless a later task explicitly authorizes a dedicated fixture write.
- Only the acquisition owner may connect to `10.11.99.1` or the USB API during the initial parallel phase.
- Never commit SSH credentials, device-derived raw files, `.rmdoc` archives, native private PDFs, rendered output, or videos.
- The coordinator owns root configuration, shared contracts, and integration. Workers must not edit `pyproject.toml`, `uv.lock`, `.python-version`, `.gitignore`, `AGENTS.md`, or `docs/contracts.md` without coordinator approval.
- Keep acquisition, parsing, replay timing, rendering, and comparison separate. The parser must not import a renderer; the replay engine must depend on a renderer interface rather than a concrete backend.
- Preserve unknown format data in diagnostic form. Keep compositing order and replay order distinct and label inferred order honestly.
- Use fixed viewports. The final replay frame must be byte-identical to static output from the same backend and options.
- Put generated or private artifacts only under ignored paths. Do not modify raw snapshots.

## Device independence and readiness claims

- Never say the saved corpus is sufficient, or that the tablet can be disconnected, based only on successful downloads or parser tests. Name the scope and verify a coverage matrix for every remaining device-dependent hypothesis and tool.
- Before handoff, validate matching raw/native exports, hashes, ordered page correspondence, nonblank native controls, geometry, tool/channel/overlap coverage, and run the actual offline render/comparison consumers. Record missing cases explicitly; experimental profiles are not native-calibrated fidelity.
- Batch missing fixtures while the device is available. Preserve prepared input and repeated native/raw readbacks with provenance. A rejected or blank fixture does not satisfy coverage; resolve it before declaring capture complete.
- After a new fixture import, resolve the device-assigned document ID and verify its listed file type and saved page contents before native export. Preserve timed-out attempts; do not repeat an upload because an export failed. Use bounded, sequential export requests and distinguish initialization/export errors from connectivity failures.
- A network-sandbox failure is not evidence that the tablet is disconnected. Retry a bounded read-only probe with the permitted network execution context before diagnosing connectivity. Keep one acquisition owner and distinguish sandbox restrictions, USB service errors, and actual reachability.
- Maintain an ignored capture readiness report listing acquired, validated, rejected, and missing cases. Only say a specific offline phase is ready after every required case for that phase passes; never generalize that claim to future work.
- The current capture acceptance is `fixtures/private/controlled-anchor-analysis/capture-20260924/READINESS.md` with `readiness.json` and provenance alongside. Consult it before requesting another device session; prepared fixture manifests describe source packages, not current capture status.

Initial exclusive source ownership:

- Acquisition: `src/rm_redraw/acquisition/`, `tests/acquisition/`
- Parser/normalization: `src/rm_redraw/parsing/`, `tests/parsing/`
- Replay/render/video: `src/rm_redraw/replay/`, `src/rm_redraw/rendering/`, `tests/replay/`, `tests/rendering/`
- Coordinator: shared/root files and cross-module integration

- Additional current-pencil pressure/angle capture acceptance: `fixtures/private/controlled-anchor-analysis/pressure-angle-capture-20260925/READINESS.md`. This supplements the earlier capture scopes; consult both before requesting a device session.
