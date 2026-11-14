# Hosted rePlay

Production: https://replay-phi-liard.vercel.app/
Vercel project: `domjanciks-projects/replay`.

The hosted build reuses the notebook gallery, encrypted cloud vault, queue, selected-page replay list, and crop/loop controls. No local Python, FFmpeg, or CLI is required. The optional USB companion remains separate.

## Data and execution

- Cloud pairing credentials and verified tree cache live in the existing encrypted IndexedDB vault. The passphrase never leaves the browser. Pair separately on each origin; a localhost vault is not migrated.
- A fixed-operation, same-origin Vercel relay streams requests to reMarkable. It necessarily sees provider tokens and downloaded bytes in transit, but does not log bodies, persist credentials, or save documents. Provider credentials are supplied per request. Redirects and arbitrary upstream URLs are refused; responses are bounded and marked no-store.
- Imports and generated images/videos live unencrypted in this browser's IndexedDB library. Browser storage clearing removes them. Save valuable output using the download controls. One editing tab owns the library through Web Locks to prevent concurrent queue overwrites.
- The worker uses Pyodide 0.29.5 with the existing Python parser/normalizer, then Rust/WASM replay scheduling and rasterization and the WebCodecs/Mediabunny encoder. It does not use a server renderer. Runtime assets are served by this deployment.
- Text-anchored pages can use an attached matching native PDF. PDF.js 6.5.438 extracts vector ink in the browser, excluding text; Rust/WASM performs distance transforms, translation search and confidence checks. The PDF remains in IndexedDB. Accepted results record its SHA-256 and matching evidence in the replay manifest. No SciPy or Poppler is needed in this path.
- Keep the tab open while work runs. Closing it interrupts active/pending jobs; completed output remains saved. Eight queued/running jobs are allowed. Output is bounded to 12 megapixels, with browser codec support checked at runtime. MP4 falls back to WebM when needed. Video buffering is capped at 64 MiB.
- Crop/loop exports rerender the source locally to avoid saving every lossless frame. Compositing stays independent of replay order. The final forward RGBA frame must equal static output.

## Current limits

Anchor matching still requires the corresponding native export and matching source canvas. Ambiguous matches, conflicting shared anchors, missing direct stroke templates, unsupported transforms, image/form content, annotations and rotated references fail explicitly. This does not infer native typography from raw strokes alone. Templates and PDF backgrounds are omitted. Parsing still uses Pyodide. Browser/mobile codec and memory capabilities vary. The relay implements the unofficial cloud protocol; a fresh live account pairing/download is still a user validation step. Localhost cloud data and private drawings were not uploaded during deployment.

## Build and deploy

1. Build both `native/renderer` and `native/replay-core` for `wasm32-unknown-unknown --release` (see their documentation).
2. Obtain the pinned Pyodide assets with `native/browser-prototype/fetch-runtime.ps1` and install the video prototype's locked build dependencies. Copy `native/hosted/package.json` and its lockfile into `artifacts/hosted-dependencies`, then run `npm ci --prefix artifacts/hosted-dependencies --ignore-scripts` for PDF.js.
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
