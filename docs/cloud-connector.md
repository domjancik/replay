# Browser cloud connection

Choose **Cloud notebooks**, open **Get a pairing code** on the official reMarkable account page, paste its eight-character code, and select how to keep the connection. Connecting opens the gallery and loads notebooks automatically. Returning users unlock the saved connection; cached notebooks appear immediately while the list refreshes.

| Choice | Saved in this browser | Returning visit |
| --- | --- | --- |
| Passkey (preferred where available) | Encrypted cloud credential and notebook list | Unlock with the same passkey |
| Password | Encrypted cloud credential and notebook list | Enter the browser unlock password |
| Session only | Nothing from the connection | Pair again |
| Without protection (explicit acknowledgement) | **Unencrypted credential and notebook list** | Open without an unlock prompt |

Unprotected storage exposes the credential to anyone with access to the browser profile, malicious same-origin code, extensions with access, or copied browser data. The credential can authorize cloud changes even though rePlay only reads documents. Closing an unprotected connection does not protect its saved data. This option is never selected automatically.

Password protection uses the existing PBKDF2-SHA256 (600,000 iterations) and AES-256-GCM format. Existing password records remain readable without migration. Passkey protection uses WebAuthn PRF plus HKDF-SHA256 and AES-256-GCM with authenticated credential/salt metadata. Only the public credential ID, random salt, IV and ciphertext are persisted. The derived key is nonextractable and held in memory; raw PRF output is cleared. The passkey is scoped to the current host (no parent-domain RP override). No rePlay server account or credential database is required.

Passkey setup creates a credential and immediately verifies that it can supply the encryption secret through an assertion, so two device prompts may appear. This happens before consuming the cloud pairing code. Cancellation or unsupported PRF leaves the code available and offers **Use a password instead**, never a silent downgrade. A passkey created before a failed setup may remain in the user's password manager. Removing the saved connection does not delete that passkey. See the [WebAuthn PRF specification](https://w3c.github.io/webauthn/#prf-extension).

Password fallback is a separate setup option, not a way to unlock an existing passkey-encrypted record. Losing the passkey/password requires removing the saved connection and pairing again. Switching protection methods currently also requires reconnecting. Synced passkeys do not synchronize the browser's connection data. Clearing site data or changing site origin requires pairing again; browser persistence is best-effort. Existing rmctl profiles are not migrated or modified.

Protected connections lock after five minutes without app interaction, explicit lock, or page exit. Session-only and unprotected sessions end on page exit or explicit close; session-only requires another pairing code afterward. Failed browser saves allow retrying or continuing session-only without registering twice. **Disconnect from reMarkable** revokes the registration and removes saved connection data; **Remove saved connection only** does not revoke. Neither removes imported drawings/videos.

The same-origin fixed-operation relay forwards requests and sees credentials transiently, but does not save credentials, notebook lists or document bytes. The browser verifies downloaded hashes. Hosted parsing and rendering run in Rust/WASM; the local utility imports into its local library. Imported drawings/videos persist separately and are not encrypted by the connection's passkey/password. A locked encrypted record is protected against storage inspection, not malicious page code running while unlocked. Keep strict CSP and self-hosted scripts; do not add analytics on the credential origin.

Automatic notebook previews load only as cards become visible and show local card progress. They do not refresh the entire cloud list or replace the connection status. The gallery is the sole notebook browser; connection settings manage only the connection.

Validation uses synthetic tokens, fake provider responses, real WebCrypto encryption, and simulated WebAuthn credentials. Actual hardware/password-manager PRF and live reMarkable pairing need user testing; no real account was paired during this change. The unofficial provider protocol may change.

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
