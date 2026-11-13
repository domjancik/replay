# Import from reMarkable Cloud

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
