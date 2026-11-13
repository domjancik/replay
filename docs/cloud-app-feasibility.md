# reMarkable Cloud import and browser replay

*Feasibility review, November 13, 2026.*

The loopback prototype browses and fetches one selected cloud document through an installed `rmctl` companion, then passes a validated archive to the existing local replay pipeline. It uses a profile the user manages in `rmctl`. In-app pairing and revocation are proposed follow-up work. Browser rendering can progress independently. The direct website-to-cloud route failed the credential-free preflights described below.

## Cloud transport evidence

reMarkable documents a one-time verification code for pairing its own desktop app. Third-party clients reuse the desktop code from the official account page. The pairing requests and cloud sync protocol below come from community client implementations. The official documentation reviewed did not establish a public OAuth client-registration flow, redirect URIs or a delegated read-only scope. The credential class used by these clients can also write documents. An rm-redraw connector would enforce its own read-only document operations. [Official desktop pairing](https://support.remarkable.com/s/article/About-the-Desktop-app) · [Desktop code page](https://my.remarkable.com/device/desktop/connect) · [Community sync client source](https://github.com/SamMorrowDrums/remarkable-mcp/blob/main/remarkable_mcp/sync.py) · [rmcloud-go v1.0.0](https://github.com/altessa-s/rmcloud-go/tree/v1.0.0)

| Operation | Evidence from community clients |
| --- | --- |
| Register a local app instance | `POST https://webapp-prod.cloud.remarkable.engineering/token/json/2/device/new` exchanges the eight-character code, client kind and generated device identifier for a durable device token. The account password stays on the official site. |
| Establish a session | `POST https://webapp-prod.cloud.remarkable.engineering/token/json/2/user/new` exchanges the device bearer for a shorter-lived user bearer. Cache the session and refresh on an authorization failure once. |
| Discover the library | `GET https://internal.cloud.remarkable.com/sync/v4/root` returns a content-addressed root and generation in the Python implementation. The Go implementation also supports v3 fallback and regional host discovery at `discovery/v1/endpoints`. |
| Fetch a selected notebook | `GET …/sync/v3/files/{hash}` reads the root index, selected document index and indexed members. The Python client supplies `rm-filename` on these GETs. `rmctl export` builds a tablet-layout `.rmdoc` locally from the document's members. |
| Disconnect and revoke | `rmcloud-go` distinguishes local `ForgetDevice` from upstream `RevokeDevice` and documents `token/json/3/device/delete`. `rmctl logout --revoke` removes the cloud registration before clearing its local profile credential. |

The `rm-filename` header became required after older clients had worked without it. A `400` can indicate protocol drift. Official tablet/app sync is available without Connect, with a 50-day inactivity limit on synced documents. `remarkable-mcp` documents Connect as required for its cloud mode. A free-account pairing and complete notebook read through the proposed connector remain unverified. Public quota and service-level guarantees for this protocol were also unavailable. [Client source](https://github.com/SamMorrowDrums/remarkable-mcp/blob/main/remarkable_mcp/sync.py) · [Header compatibility incident](https://github.com/SamMorrowDrums/remarkable-mcp/issues/92) · [Official cloud and Connect limits](https://support.remarkable.com/s/article/How-do-I-pair-my-reMarkable-with-the-cloud) · [remarkable-mcp Cloud Mode](https://github.com/SamMorrowDrums/remarkable-mcp#cloud-mode)

The official account and Connect terms links returned a support-page error during this review. Whether they permit a publicly operated third-party connector remains open. Review the applicable terms and ask reMarkable about supported third-party access before offering an independent hosted integration. The code's MIT license governs the code and does not grant rights to the cloud service. [reMarkable account terms](https://support.remarkable.com/s/article/Terms-and-Conditions-for-reMarkable-Accounts) · [Connect terms](https://support.remarkable.com/s/article/Terms-and-Conditions-for-Connect) · [Official legal overview](https://support.remarkable.com/s/legal)

## Browser and hosting boundary

On November 13 at 12:38 UTC, two credential-free `OPTIONS` requests used `Origin: https://rm-redraw.example`. The auth registration preflight for `POST` with `authorization,content-type` returned HTTP 405. The v4 sync root preflight for `GET` with `authorization` returned HTTP 400. Both omitted CORS allow headers. The initial restricted context could not resolve either host. The reported responses came from the permitted network context. The browser would reject these requests for that origin. WASM runs inside the browser's network security model. Other hosts and origins were outside this probe. [Fetch CORS protocol](https://fetch.spec.whatwg.org/#http-cors-protocol)

| Path | Credential and cost model |
| --- | --- |
| Local app and local connector | The user keeps the connector and token on their computer. The browser uses the existing same-origin loopback service. No operator-side render compute, credential store, or document relay is required. |
| Static browser app with file import | The user supplies an exported `.rmdoc` or `.rm`. Local processing needs no cloud credentials and can be distributed as static assets. Browser import, normalization and worker rendering still need implementation and verification. |
| Public web app with cloud broker | A same-origin broker can make outbound provider requests and stream the selected archive to the browser. It can see notebook bytes and holds an account-capable credential. That entails session isolation, encrypted credential handling, revocation, bandwidth, rate limits and operations. Browser-side rendering only removes server rasterization and encoding costs. |

## Implemented loopback prototype

The prototype targets user-installed `rmctl` **v1.2.0** from release commit `7e9daaa`. The lite build retains the required commands, including on Windows. The app leaves profile selection to `rmctl`, which uses its default profile unless the local environment configures another. A real release binary and a live account were outside this review. [Release list](https://github.com/altessa-s/rmctl/releases) · [Pinned browse commands](https://github.com/altessa-s/rmctl/blob/v1.2.0/cmd/rmctl/commands/browse/cmd.go) · [Pinned listing output](https://github.com/altessa-s/rmctl/blob/v1.2.0/cmd/rmctl/commands/cliutil/output.go) · [Pinned export command](https://github.com/altessa-s/rmctl/blob/v1.2.0/cmd/rmctl/commands/fetch/cmd.go)

| Local app operation | Connector contract |
| --- | --- |
| Cloud status | The app reports whether it found an executable on an absolute `PATH` entry. This check launches no process and makes no network request. Browsing surfaces an unregistered profile when `rmctl` returns exit 3. |
| Browse cloud | `rmctl --offline=false --no-cache --json find` emits a flat array. The app keeps visible `notebook` and `annotated-pdf` rows and returns `id`, `name`, `path` and `kind`. |
| Import selected document | With the same global flags, the app runs `stat <uuid>` before `export <uuid> -o <temporary-path>/selected.rmdoc`. It verifies the UUID, supported kind, visibility and a reported size within the 128 MiB limit. Export must report one document, and the archive must pass the size, member-hash and selected-document checks. The existing importer records `rmctl-cloud` provenance. A paired native PDF can be attached separately. |

The prototype runs a fixed command list without a shell, disables the companion cache, bounds request time and stages exports in local temporary storage. Listing can read indexes and metadata for the whole library. Page data is requested for the selected document. The current validation uses fake process responses and synthetic archives. A dedicated account is needed to verify the live registration, list, export and replay sequence. [Pinned profile and cache docs](https://github.com/altessa-s/rmctl/blob/v1.2.0/docs/configuration.md) · [Pinned archive behavior](https://github.com/altessa-s/rmctl/blob/v1.2.0/docs/pages-and-archives.md)

## Planned in-app pairing and revocation

The shipped `rmctl register` requires one positional code and offers no stdin prompt. A small upstream patch adding an explicit stdin mode could reuse its profile and revocation implementation. A standalone helper could instead call `rmcloud-go` v1.0.0 `RegisterDevice` with a user-local `SecretStore` and own the rest of the provider's session. The browser would submit the short-lived code through the authenticated loopback service. Keep credentials out of process arguments, URLs, logs and persistent browser storage. [Pinned registration command](https://github.com/altessa-s/rmctl/blob/v1.2.0/cmd/rmctl/commands/account/cmd.go) · [Pinned Go account API](https://github.com/altessa-s/rmcloud-go/blob/v1.0.0/account.go)

`rmctl` keeps `token.json` in the local profile by default and offers a macOS Keychain backend. Plain `logout` clears local profile credentials and cache. `logout --revoke` first removes the cloud registration. An in-app revoke action should report upstream failure explicitly. Imported archives stay in the local library until the user removes them. [Pinned profile and cache docs](https://github.com/altessa-s/rmctl/blob/v1.2.0/docs/configuration.md)

## Local browser rendering milestone

Begin with a synthetic normalized page fed into a Web Worker. Load the Rust pencil kernel once and render reached strokes into retained buffers. Present the worker's RGBA buffer through a canvas and compare it with the Python reference at several progress points. Measure wall time and peak memory on a desktop and a representative mobile browser. The installed `wasm32-unknown-unknown` target makes compilation possible in this workspace. It does not establish browser bindings, performance or renderer equivalence.

The native Rust kernel only computes current-pencil coverage. The browser host still needs normalization, stroke sampling, pressure/lookup data, layers, erasers, fixed viewport, source-resolution composition and final downsampling. Preserve ordered source-over and compare static and final RGBA bytes. This avoids conflating pixel equality with PNG encoder differences across runtimes. Once interactive playback works, feature-detect WebCodecs and provide an explicit container muxer for supported download formats. WebCodecs itself does not guarantee any specific codec. Keep local FFmpeg export available while validating browser codecs and muxing. [Existing pencil kernel](../native/pencil-kernel/README.md) · [WebCodecs working draft](https://www.w3.org/TR/2026/WD-webcodecs-20261109/) · [HTML canvas standard](https://html.spec.whatwg.org/multipage/canvas.html#the-offscreencanvas-interface)

Rendering locally can make a no-fee app plausible. Serving static assets still uses hosting and bandwidth. A hosted credential broker adds private-data obligations and infrastructure, and reMarkable's account plan governs its own cloud availability. Keep manual import available as an independent path.
