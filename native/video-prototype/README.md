# Browser video encoding probe

The worker encodes synthetic RGBA frames with the browser's WebCodecs encoder and muxes the result in the same worker using Mediabunny. The harness plays, seeks and downloads the output as a local Blob. It uses no notebook data and sends no frames to a service.

`browser.mjs` exports `encodeReplay({ frames, width, height, fps, frameCount, signal, onProgress, container, maxBytes })`. The frame iterator supplies precomposited, opaque RGBA bytes in schedule order. The encoder assigns frame `i` the timestamp `i / fps` and duration `1 / fps`, and awaits the muxer between submissions. `container` can be `auto`, `mp4` or `webm`. Automatic selection tries MP4/AVC, then WebM/VP9, then WebM/VP8, using the actual browser's encoding capabilities. The result contains `buffer`, `mimeType`, `extension`, `codec` and `frameCount`. Browser codecs can produce different lossy bytes. Validate renderer output on its original RGBA buffers.

This probe accepts even dimensions up to 1280 per axis and at most 921,600 pixels, 1–30 fps, and up to 60 seconds. Its seekable sink caps output at 64 MiB before copying incoming chunks. Encoder surfaces and temporary buffers add memory beyond the cap. The final trim can briefly retain both the backing buffer and the result. Cancellation is cooperative between frame submissions and also works if the consumer aborts during initialization or finalization. A producer that waits on I/O should observe the same signal. For longer export, investigate a local seekable file target and verify memory on representative devices.

## Run locally

From the repository root in PowerShell, with Node and npm available:

```powershell
$videoProbe = 'artifacts/video-prototype-20261113'
$videoDeps = Join-Path $videoProbe 'dependencies'
New-Item -ItemType Directory -Force $videoDeps | Out-Null
Copy-Item 'native/video-prototype/package*.json' $videoDeps
npm.cmd ci --prefix $videoDeps --ignore-scripts --no-audit --no-fund
node native/video-prototype/build.mjs
node --test native/video-prototype/encode.test.mjs
```

Serve the ignored `site` directory on loopback and open `harness.html` in a browser with WebCodecs. The automated smoke uses installed Chrome, Playwright and `ffprobe`. It starts and stops its own localhost server.

```powershell
npm.cmd install --prefix (Join-Path $videoProbe 'browser-qa') --ignore-scripts --no-audit --no-fund --save-exact playwright@1.65.0
node native/video-prototype/smoke.mjs
```

On Windows, Chrome 152.0.7977.77 encoded and downloaded both H.264/MP4 and VP9/WebM at 96×72. `ffprobe` counted all 29 frames at 12 fps in each output. Chrome played and sought within both videos. The smoke verified cancellation and observed no requests outside its local origin. Larger inputs, mobile browsers and VP8 fallback encoding remain unmeasured by this test.

## Distribution

`mediabunny@1.65.2` is an MPL-2.0 dependency. `esbuild@0.28.2` is an MIT build tool. Both are pinned in the lockfile. The build preserves legal comments and copies the Mediabunny license into the ignored site. A redistributed JS bundle must retain those notices and make the corresponding Mediabunny source, including any modifications, available under MPL-2.0. The rm-redraw source remains MIT. The generated bundle and videos are local research artifacts. [Mediabunny v1.65.2 source](https://github.com/Vanilagy/mediabunny/tree/v1.65.2) · [Mozilla MPL distribution guidance](https://www.mozilla.org/en-US/MPL/2.0/FAQ/)
