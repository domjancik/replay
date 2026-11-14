# Hosted rePlay

Production: https://replay.domj.net/
Vercel alias: https://replay-phi-liard.vercel.app/
Vercel project: `domjanciks-projects/replay`.

The hosted build reuses the notebook gallery, browser-owned cloud connection, queue, selected-page replay list, and crop/loop controls. No local Python, FFmpeg, or CLI is required. The optional USB companion remains separate.

## Data and execution

- Cloud pairing credentials and the verified notebook cache use the selected browser storage mode: passkey encryption (preferred where supported), password encryption, session-only memory, or explicitly acknowledged unprotected IndexedDB. Passwords and passkey-derived secrets never leave the browser. Pair separately on each origin; a localhost connection is not migrated.
- A fixed-operation, same-origin Vercel relay streams requests to reMarkable. It necessarily sees provider tokens and downloaded bytes in transit, but does not log bodies, persist credentials, or save documents. Provider credentials are supplied per request. Redirects and arbitrary upstream URLs are refused; responses are bounded and marked no-store.
- Imports and generated images/videos live unencrypted in this browser's IndexedDB library. Browser storage clearing removes them. Save valuable output using the download controls. One editing tab owns the library through Web Locks to prevent concurrent queue overwrites.
- The worker uses the standalone `rm-rmdoc` Rust/WASM archive reader, v5/v6 parser and normalizer, then Rust/WASM replay scheduling and rasterization and the WebCodecs/Mediabunny encoder. No Python runtime or Python wheels are deployed. It does not use a server renderer. Runtime assets are served by this deployment.
- Text-anchored pages can use an attached matching native PDF. PDF.js 6.5.438 extracts vector ink in the browser, excluding text; Rust/WASM performs distance transforms, translation search and confidence checks. The PDF remains in IndexedDB. Accepted results record its SHA-256 and matching evidence in the replay manifest. No SciPy or Poppler is needed in this path.
- Keep the tab open while work runs. Closing it interrupts active/pending jobs; completed output remains saved. Eight queued/running jobs are allowed. Output is bounded to 12 megapixels, with browser codec support checked at runtime. MP4 falls back to WebM when needed. Video buffering is capped at 64 MiB.
- Crop/loop exports rerender the source locally to avoid saving every lossless frame. Compositing stays independent of replay order. The final forward RGBA frame must equal static output.

## Current limits

Anchor matching still requires the corresponding native export and matching source canvas. Ambiguous matches, conflicting shared anchors, missing direct stroke templates, unsupported transforms, image/form content, annotations and rotated references fail explicitly. This does not infer native typography from raw strokes alone. Templates and PDF backgrounds are omitted. The reader rejects unknown major file versions, unsupported geometry blocks and ZIP64 directories explicitly; preserved diagnostics support future format updates. Browser/mobile codec and memory capabilities vary. The relay implements the unofficial cloud protocol; a fresh live account pairing/download is still a user validation step. Localhost cloud data and private drawings were not uploaded during deployment.

## Build and deploy

1. Build `native/redraw`, `native/replay-core` and `native/rmdoc` for `wasm32-unknown-unknown --release` (see their documentation).
2. Install the video prototype's locked build dependencies. Copy `native/hosted/package.json` and its lockfile into `artifacts/hosted-dependencies`, then run `npm ci --prefix artifacts/hosted-dependencies --ignore-scripts` for PDF.js.
3. Run `node native/video-prototype/build.mjs` and `.venv/Scripts/python.exe native/hosted/build.py`.
4. Inspect `artifacts/hosted-replay`: only `public/`, the fixed relay, and deployment configuration belong there. User fixtures are never copied. Never deploy the repository root.
5. In that directory run `npx vercel deploy --prod`. The ignored `.vercel` linkage identifies the project.

## Validation (November 13, 2026)

- Browser worker imported synthetic v5 and mixed-tool v6 archives, rendered frames, encoded videos, and recovered saved library records.
- Production HTTPS app imported a synthetic v6 notebook, generated a 42-frame replay, and exported a quick-reverse loop. Saved image/video links used browser blob URLs.
- Public health returned 200; cross-origin relay requests returned 403; an intentionally invalid provider session returned 401 without exposing the token or provider body.
- Backend/browser tests cover clipping, unsupported anchors, replay ordering, encoded dimensions, relay destination restrictions, cloud vault handling, and existing app workflows.
- Rust/WASM matches Python on seven synthetic anchor cases, two fits from a saved private native export, and six entry/layer replay schedules. A browser test attached a synthetic native PDF, resolved its anchor, rendered and encoded an 18-frame replay with final/static equality and reference provenance.

These tests establish the browser deployment path, not universal native fidelity or live account pairing success.

## Native reader migration (November 14, 2026)

The Python bridge remains a development oracle, not a deployed dependency. The build removes the old generated runtime directory. The independent reader crate exposes archive inspection, diagnostic parsing and renderer projection; it does not acquire data or import the renderer. See `native/rmdoc/README.md` and `FORMAT_UPDATES.md` for usage, bounds and the update procedure.

WASM differential validation covers 46 pages and 184 parse/info/prepare/anchor comparisons, including synthetic malformed/unknown cases, 19 controlled pages and four natural pages. Unknown-geometry rejection is an intentional stricter behavior. Diagnostic framing and explanatory prose differ; geometry, channels, visibility, identifiers and ordering are compared. Private fixtures remain local.

The final migration checks passed 30 Rust tests (including the package usage example and exact decoded-block oracle), 172 relevant Python tests and 47 browser JavaScript tests. There are also 23 explicit-layout projection comparisons. Pixel checks cover 6 synthetic, 19 controlled and 3 natural successful preparations (including birthday page 12): all 28 outputs match, and all final/static checks pass. The fourth natural page remains explicitly unresolved and is not counted as a pixel success. The Python-free local browser exercised v5/v6 import, native-PDF anchors, preview, video, crop and reverse loops. Cargo package verification and Clippy passed.

Deployed November 14 after Vercel sign-in was restored: `dpl_GSC3RVjU8hcet3G7CE1oNd2Rqj8Z`. Public HTTPS checks on `replay.domj.net` returned 200 for the app, native worker and reader WASM. The deployed reader SHA-256 matches the locally tested binary and has no host imports. The removed `/runtime/pyodide.mjs` returns 404.


## Connection simplification and passkeys (November 14, 2026)

Implementation commit `c553ab7` adds the four storage choices, an explicit unprotected-storage warning/acknowledgement, distinct connect/unlock/settings views, automatic notebook loading, and card-local lazy preview progress. Existing version-1 password records remain supported. Passkey PRF encryption is tested before cloud pairing; unsupported or cancelled setup never silently downgrades protection.

Validation passed 55 web JavaScript tests, 6 hosted JavaScript tests, 77 web/release Python tests and 4 hosted Python tests. The hosted build and Ruff check passed. Local browser checks covered all four storage choices and the warning; production verified the passkey-first screen. WebAuthn tests use simulated authenticator responses with real WebCrypto. Real device/password-manager PRF and a fresh real cloud pairing remain unverified.

Deployed as `dpl_rucwtvwjCaZxcST6GH4cMg8dVzKY` to `https://replay.domj.net/`. Public checks confirmed the new interface and passkey vault source. Deployment contains app code only; no private drawings or pairing data were uploaded.
