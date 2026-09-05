# Agent kickoff readiness

Verified 2026-09-05. Ready to start acquisition, parser, and baseline replay work after a coordinator establishes the repository and shared contracts. The user subsequently enabled the USB web interface: listing, raw export, and native PDF export now work. No implementation or dependency installation was performed during verification.

## USB API follow-up verification

- `/documents/` returned HTTP 200 and 109 root records; the root Drawings UUID matches SSH metadata.
- `/documents/6694e399-2a32-4b35-abef-e036cb77d069` returned HTTP 200 and 61 immediate children (not the recursive document count).
- Sample notebook `8aba68ff-00e9-400b-9772-b96322e000f0`: raw export returned HTTP 200, 3,549,833 bytes, valid ZIP CRC checks, and five `.rm` files.
- The same notebook's `/placeholder` export returned HTTP 200, 7,896,850 bytes, `application/pdf`, a PDF signature and EOF marker. Full PDF parsing/rasterization and correspondence checks remain implementation work.
- Downloads were inspected in memory, not saved as a durable fixture. The earlier port-80 blocker below is historical and resolved.
- Environment correction: `pypdf` was discoverable in the earlier sandbox interpreter but not importable in the elevated command environment. Pin the Python executable/environment explicitly during setup; do not assume package availability transfers between execution environments.

## Verified environment and device

- Direct noninteractive SSH works: `ssh -o BatchMode=yes 10.11.99.1`. Local SSH configuration selects the existing passwordless key. Do not copy private keys into this project.
- Device reports `reMarkable Chiappa`, firmware image `3.27.3.0`, OS version `5.7.126`. Marketing model and page dimensions have not been inferred from the codename.
- Native store exists at `/home/root/.local/share/remarkable/xochitl/`.
- Read 859 metadata records and corresponding content records into local memory, without changing device files.
- Root Drawings collection UUID: `6694e399-2a32-4b35-abef-e036cb77d069`. It has 100 descendants, including 96 non-deleted document records: 95 notebooks and one PDF. Acquisition must additionally enforce ancestor/trash semantics.
- Two other items share the name Drawings: one notebook and an empty nested collection. Select the root collection by UUID, not the first name match.
- Six page headers sampled from notebook `1f7a7562-680e-452d-a9f7-da2c23e8717a` were `.rm` version 6. This is not an inventory of every page or pen.
- Device has `tar`, `sha256sum`, and `dd`. `python3` and `curl` were not found on its PATH. BusyBox `head` does not support `-c`; use `dd` for bounded byte reads.
- HTTP request to `http://10.11.99.1/documents/` failed; `/proc/net/tcp` and `/proc/net/tcp6` showed no port 80 listener. USB API exports are unverified and currently unavailable.
- Local Git 2.47.1, Node 26.4.0/npm 11.17.0, FFmpeg 7.1 with libx264, and Poppler pdftoppm 26.07.0 execute. GitHub CLI is authenticated. The project uses uv-managed CPython 3.13.15, the current 3.13 maintenance release as of 2026-09-05.
- PIL, numpy, skimage, and pypdf are discoverable in the local Python interpreter. rmscene and rmc are absent there. No project dependency environment exists yet.
- At initial inspection the workspace contained only the brief and was not a Git repository. This document is the only review artifact added. No applicable ancestor AGENTS.md was found.

## Launch order and ownership

1. Coordinator: initialize repository/environment when implementation starts; choose and pin runtime/dependencies after a small parser/render smoke test; own shared contracts, CLI, root config, and integration.
2. Acquisition agent: own acquisition and corpus modules. Sole device operator. Implement stable, hashed read-only snapshots from the root Drawings UUID. Later own USB raw/PDF acquisition. Gate: an immutable snapshot with page mapping and complete file hashes.
3. Parser agent: own parser adapters and diagnostic export. Evaluate existing implementations against actual snapshots, retain raw channels and unknown fields, separate scene ordering from replay ordering. Gate: diagnostic JSON and metadata-retention tests on real v6 samples.
4. Replay agent: own baseline render adapter, replay scheduling, compositing, frame output, and encoding. Start synthetic contract fixtures while acquisition/parser work proceeds. Gate: deterministic stroke-step and progressive frame sequences, fixed viewport, correct layers, and final frame identical to static output.

Run steps 2-4 concurrently only after shared contracts are established. Reference evaluation can overlap coordinator setup. With four total agent slots, retain coordinator plus these three workers. After baseline replay, reassign the parser slot to comparison tooling and fixture analysis, then renderer research. Do not have multiple agents concurrently tune the same pen-rendering core.

For separate Git worktree tasks, establish and commit the shared scaffold before creating those tasks. Each worker owns its modules and tests; shared contract changes go through the coordinator. The local corpus needs an agreed shared read-only location accessible from each worktree.

## Contracts to freeze

- Versioned snapshot manifest: source identity, firmware, document/page IDs and order, filenames, hashes, acquisition time and stability evidence.
- Normalized page: dimensions and explicit transforms, groups/layers, raw point channels, CRDT IDs, moves/tombstones, unknown fields, and separate compositing/replay orders with uncertainty and fallback policy.
- Renderer: immutable visibility/progress state, fixed viewport, deterministic texture inputs, one static/frame render path.
- Comparison: fixed rasterizer/version/settings, dimensions/colour/background/crop, per-pen and ink-ROI metrics.
- Canonical corpus paths: use `raw/`, `native/`, `rendered/`, `diff/` consistently; resolve the brief's alternate `reference/` example.

## Remaining work, not kickoff blockers

- Capture a durable corpus; verify snapshot stability and parse real files. Only metadata and page headers were inspected during verification.
- Test dependency installation and Windows renderer compatibility in a project environment; executables on PATH do not prove pipeline compatibility.
- Determine actual geometry, pen inventory, backgrounds/templates/text scope, numeric fidelity thresholds, and frame versus encoded-video determinism.
- USB API connectivity and both export routes are now verified. Next capture durable paired exports and validate page correspondence and rasterization. Do not restart xochitl or modify settings as part of read-only verification.
- Device fixture writes require explicit opt-in and must use dedicated fixture documents. Existing Drawings remain read-only.

## Reference preflight

Repository documentation was inspected, not installed or executed. Pin exact revisions and inspect relevant code before implementation. Root license labels are not a complete dependency license audit.

- [rmscene](https://github.com/ricklupton/rmscene): MIT, v6 parsing; documented SceneInfo/paper_size, move/tombstone handling and retained unparsed data make it a strong parser candidate.
- [rmc](https://github.com/ricklupton/rmc): MIT, v6 conversion candidate.
- [remarkable-rm](https://github.com/Scratchydisk/remarkable-rm): MIT, TypeScript parser/render candidate.
- [librm_lines](https://github.com/RedTTGMoss/librm_lines) and [pylibrm_lines](https://github.com/RedTTGMoss/pylibrm_lines): GPL-3.0; evaluate reuse deliberately before adopting code/dependencies.
- [Quill](https://github.com/CrimsonAS/quill): BSD-3-Clause, variable-width stroking reference.
- [remarkable-mcp](https://github.com/SamMorrowDrums/remarkable-mcp): MIT root license; relevant acquisition/authoring code still needs detailed review.
- [USB API documentation](https://github.com/Scratchydisk/remarkable-rm/blob/main/docs/remarkable-usb-api.md): documents enabling the interface under Settings > Storage and raw/native PDF routes; documented tests were on firmware 3.26, so verify on this tablet's 3.27.3.0.

Follow brief milestone acceptance order: SSH snapshots -> diagnostics -> replay -> USB pairing -> comparison -> controlled corpus -> simple pens -> pencil -> other tools -> replay texture stability.

Dependency validation found that current `rmc==0.3.0` requires `rmscene>=0.6,<0.7`, which conflicts with current `rmscene==0.8.0`. The main project pins `rmscene==0.8.0` and excludes `rmc`; evaluate `rmc` only in an isolated reference environment unless its dependency range changes.

CPython calls 3.13 a bugfix/maintenance branch at this date, not an LTS channel. Its scheduled end of life is October 2029; security-only support is a later lifecycle phase. The initially installed 3.13.7 came from a stale uv 0.8.12 catalog and was superseded, so uv was updated to 0.12.10 and the exact runtime pin corrected to 3.13.15.
