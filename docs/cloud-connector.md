# Import from reMarkable Cloud

The local replay app can browse synced notebooks and annotated PDFs through a user-installed rmctl companion. It saves the selected document as a local `.rmdoc`. Choose an ink page in the local library to make a replay and export an MP4.

## Set up the companion

1. Download rmctl or rmctl-lite **v1.2.0** for your OS and architecture. Both use the same `rmctl` command. Put its executable in an absolute directory on your `PATH`. [Upstream release and checksums](https://github.com/altessa-s/rmctl/releases/tag/v1.2.0)
2. In your own terminal, follow the upstream registration instructions with a one-time desktop code from your reMarkable account. rmctl v1.2.0 takes the code as a command-line argument. Use a private terminal and avoid retaining the command in shell history. [rmctl registration instructions](https://github.com/altessa-s/rmctl/blob/v1.2.0/README.md#quick-start) · [reMarkable desktop code](https://my.remarkable.com/device/desktop/connect)
3. Start the local replay app from the environment that can find rmctl. If you registered a named profile, set `RMCTL_PROFILE` to that profile before launching the app. Choose **Browse cloud**, select a notebook, then choose a page in the local library. [Local replay app](local-replay-utility.md) · [rmctl profile settings](https://github.com/altessa-s/rmctl/blob/v1.2.0/docs/configuration.md#profiles)

Pairing and credential storage belong to the local rmctl profile. To remove its cloud registration and local credential, follow the upstream `logout --revoke` instructions in your terminal. Imported notebooks and replay outputs remain in the local replay library. [rmctl account commands](https://github.com/altessa-s/rmctl/blob/v1.2.0/README.md#commands)

## Preview scope

The connector uses rmctl's unofficial cloud transport. The app restricts the companion to list, inspect and export operations. The rmctl profile's credential itself can authorize cloud writes. The app requests no background sync and disables the companion's content cache for its requests. Listing can still read indexes and document metadata across the library. [rmctl output and exit codes](https://github.com/altessa-s/rmctl/blob/v1.2.0/docs/output.md) · [rmctl cache behavior](https://github.com/altessa-s/rmctl/blob/v1.2.0/docs/configuration.md#cache)

The app checks the selected UUID, type, visibility and reported source size before export. It accepts one matching archive up to 128 MiB through the local import path. Metadata commands time out after 60 seconds and export after 180 seconds. rmctl stages the download locally before archive validation. Cloud imports carry raw ink and no paired native PDF. Pages that need native reference data can use the app's existing local PDF attachment workflow. [rmctl archive layout](https://github.com/altessa-s/rmctl/blob/v1.2.0/docs/pages-and-archives.md#archives)

Adapter tests use the v1.2.0 source contract and a mocked companion. Live registration, real cloud exports and behavior on an account without Connect remain unverified. [Cloud and browser feasibility](cloud-app-feasibility.md)
