# Import from reMarkable Cloud

## Current browser-owned connection

The app no longer requires rmctl or any companion CLI for cloud access. **Browse cloud** exchanges a desktop pairing code through a fixed-endpoint, stateless relay. Choose a unique vault passphrase of at least 12 characters. The browser stores the device token and verified notebook tree together in IndexedDB, encrypted with AES-256-GCM using a PBKDF2-SHA256 key (600,000 iterations and a random salt). Neither the passphrase nor the derived key is persisted or sent to the relay. Short-lived user tokens stay in memory. Reloading, closing the dialog, or five minutes of inactivity locks this tab. Unlocking restores the saved tree without a cloud request; refreshing checks the current root hash and reuses verified cached metadata.

The relay does not write credentials, pairing codes, tree indexes or downloaded blobs to disk. It sees the credential while forwarding a request: this is **no server persistence**, not end-to-end secrecy from the relay. Browser CORS restrictions still require this transport. It only allows registration, session exchange, root/file reads and explicit revocation at fixed HTTPS provider endpoints; document writes and arbitrary URLs are unavailable. Authenticated same-origin requests, bounded concurrency through response delivery, no-store responses and redacted upstream errors apply. The current Python host remains a loopback utility; deploying the relay publicly needs HTTPS, abuse limits and deployment-specific logging/crash-dump controls.

The browser verifies content hashes and assembles the selected notebook archive. **Import ink** currently sends that selected archive to the existing local replay library, which persists it and its outputs. Pairing and the tree stay browser-owned; the complete document/render pipeline is not yet browser-only.

**Revoke cloud access** revokes this registration and deletes its vault. **Forget browser vault only** deletes local pairing/cache without cloud revocation. Neither deletes imported notebooks. A forgotten passphrase requires forgetting the vault and pairing again. Browser storage is origin-specific; changing host or port uses a different vault. Persistent-storage permission is requested but not guaranteed, and clearing site data removes the vault. Existing rmctl profiles are not migrated or modified.

Encrypted storage protects a locked vault against casual storage inspection. It does not protect an unlocked token from malicious same-origin scripts, a compromised browser, or an untrusted relay. Keep the strict CSP and self-hosted scripts; do not add analytics to the credential origin. See [OWASP browser-storage guidance](https://cheatsheetseries.owasp.org/cheatsheets/HTML5_Security_Cheat_Sheet.html) and [browser persistence behavior](https://developer.mozilla.org/en-US/docs/Web/API/StorageManager/persist).

Automated tests use synthetic credentials and a fake provider. Live account pairing and exports remain unverified until exercised with a user-provided pairing code. The provider protocol is unofficial and may change.

## Historical CLI prototype (retired from the normal app)

The following describes the earlier adapter, retained as research and compatibility-test code. Its HTTP routes return 410 in the normal app; it is not a setup requirement.

The local replay app can browse synced notebooks and annotated PDFs through a user-installed rmctl companion. It saves the selected document as a local `.rmdoc`. Choose an ink page in the local library to make a replay and export an MP4.

## Set up the companion

1. Download rmctl or rmctl-lite **v1.2.0** for your OS and architecture. Both use the same `rmctl` command. Put its executable in an absolute directory on your `PATH`. [Upstream release and checksums](https://github.com/altessa-s/rmctl/releases/tag/v1.2.0)
2. To pair inside the app, build the optional `rmctl-pairing` companion and put it on the same `PATH`. The app can also browse through a profile already paired with stock rmctl. [Companion build](../native/rmctl-pairing/README.md) · [rmctl registration instructions](https://github.com/altessa-s/rmctl/blob/v1.2.0/README.md#quick-start)
3. Start the app from that environment. For a dedicated profile, set `RMCTL_PROFILE=rm-redraw` before starting the app and reserve that profile for rm-redraw. Open **Browse cloud** and use **Pair this computer** with a fresh desktop code. Once paired, select a notebook and then a page in the local library. [Local replay app](local-replay-utility.md) · [rmctl profile settings](https://github.com/altessa-s/rmctl/blob/v1.2.0/docs/configuration.md#profiles) · [reMarkable desktop code](https://my.remarkable.com/device/desktop/connect)

The app passes the code through the companion's standard input. Both executables share the selected rmctl profile. When you revoke from the cloud dialog, rmctl removes that profile's cloud registration, local credential, and cache. Any other tool using the same profile loses that connection and cache. Imported notebooks and replay outputs remain in the local replay library. [rmctl account commands](https://github.com/altessa-s/rmctl/blob/v1.2.0/README.md#commands) · [Profile cache lifecycle](https://github.com/altessa-s/rmctl/blob/v1.2.0/internal/adapter/indexcache/registry.go)

## Preview scope

The connector uses rmctl's unofficial cloud transport. The app uses rmctl to list, inspect and export documents, and to pair or revoke when requested. The rmctl profile's credential itself can authorize cloud writes. The app requests no background sync and disables the companion's content cache during reads. Listing can still read indexes and document metadata across the library. [rmctl output and exit codes](https://github.com/altessa-s/rmctl/blob/v1.2.0/docs/output.md) · [rmctl cache behavior](https://github.com/altessa-s/rmctl/blob/v1.2.0/docs/configuration.md#cache)

The app checks the selected UUID, type, visibility and reported source size before export. It accepts one matching archive up to 128 MiB through the local import path. Metadata commands time out after 60 seconds and export after 180 seconds. rmctl stages the download locally before archive validation. Cloud imports carry raw ink and no paired native PDF. Pages that need native reference data can use the app's existing local PDF attachment workflow. [rmctl archive layout](https://github.com/altessa-s/rmctl/blob/v1.2.0/docs/pages-and-archives.md#archives)

Adapter tests use the v1.2.0 source contract and a mocked companion. The patched companion builds on Windows and its account command tests use synthetic codes and fake services. Live registration, real cloud exports and behavior on an account without Connect remain unverified. [Cloud and browser feasibility](cloud-app-feasibility.md)
