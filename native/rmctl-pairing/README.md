# Build the local pairing companion

rm-redraw uses stock rmctl or rmctl-lite v1.2.0 for cloud imports. The optional pairing companion builds from the same source and adds `register --code-stdin`. Both commands use the same rmctl profile configuration. The build below uses file credential storage. For macOS Keychain, use a cgo-enabled rmctl build with the patch applied and leave `rmctl-pairing` off PATH. [Upstream configuration](https://github.com/altessa-s/rmctl/blob/v1.2.0/docs/configuration.md)

Run these commands from the rm-redraw repository in PowerShell with Git and Go available. The pinned project selects Go 1.27.3. Copy the resulting executable into an absolute directory already on your PATH, alongside the stock `rmctl.exe`.

```powershell
$patchFile = (Resolve-Path native/rmctl-pairing/code-stdin.patch).Path
git clone --depth 1 --branch v1.2.0 https://github.com/altessa-s/rmctl.git artifacts/rmctl-pairing
Set-Location artifacts/rmctl-pairing
if ((git rev-parse HEAD) -ne "7e9daaa301be788175682d5f5a755a0eb11ea6da") {
    throw "The pairing patch requires the pinned rmctl commit."
}
git apply --unidiff-zero --check $patchFile
git apply --unidiff-zero $patchFile
$env:CGO_ENABLED = "0"
go test -tags norender ./cmd/rmctl/commands/account
go build -trimpath -tags norender -o rmctl-pairing.exe ./cmd/rmctl
.\rmctl-pairing.exe register --help
```

For macOS and Linux use the same pinned checkout and patch, then run `CGO_ENABLED=0 go build -trimpath -tags norender -o rmctl-pairing ./cmd/rmctl` and place `rmctl-pairing` on PATH. The two-binary setup keeps the local pairing build compiler-free and uses the stock release for archive export. Both stock release variants include the cgo archive writer. A build with `CGO_ENABLED=0` uses the archive stub. A cgo-enabled build with this patch can handle both roles as `rmctl`. Set the same `RMCTL_PROFILE` and config environment when using either executable. The app detects `--code-stdin` through local command help. [Pinned archive wiring](https://github.com/altessa-s/rmctl/blob/v1.2.0/internal/wiring/wiring.go#L155-L162) · [Pinned cgo-disabled archive stub](https://github.com/altessa-s/rmctl/blob/v1.2.0/internal/adapter/rmdocs/stub.go)

The patch contains MIT-licensed upstream context. [License](LICENSE) · [Pinned source](https://github.com/altessa-s/rmctl/tree/7e9daaa301be788175682d5f5a755a0eb11ea6da)
