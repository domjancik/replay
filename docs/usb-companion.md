# Optional USB companion

Cloud pairing and file import do not use this companion. It is a small, separate desktop app for allowing a browser to read a USB-connected tablet. The desktop builds bundle Python and Tk; end users do not need a terminal, Python, uv, FFmpeg or a renderer installation.

## Downloads

Unsigned preview bundles, built and startup-tested on native CI runners. No Python installation is required.

| Platform | Download | Minimum build baseline |
| --- | --- | --- |
| Windows x64 | [Download](https://github.com/domjancik/replay/releases/download/companion-v0.3.1/rePlay-USB-Companion-windows-x64.zip) | Windows 10/11 x64 |
| Mac · Apple Silicon | [Download](https://github.com/domjancik/replay/releases/download/companion-v0.3.1/rePlay-USB-Companion-macos-arm64.zip) | macOS 15, Apple Silicon |
| Mac · Intel | [Download](https://github.com/domjancik/replay/releases/download/companion-v0.3.1/rePlay-USB-Companion-macos-x64.zip) | macOS 15, Intel |
| Linux x64 | [Download](https://github.com/domjancik/replay/releases/download/companion-v0.3.1/rePlay-USB-Companion-linux-x64.tar.gz) | Ubuntu 22.04 / glibc 2.35, X11/XWayland |
| Linux ARM64 | [Download](https://github.com/domjancik/replay/releases/download/companion-v0.3.1/rePlay-USB-Companion-linux-arm64.tar.gz) | Ubuntu 24.04 / glibc 2.39, X11/XWayland |

[Release notes and per-download SHA-256 checksums](https://github.com/domjancik/replay/releases/tag/companion-v0.3.1).

### Open the companion

- **Windows:** Extract the ZIP completely, then open `rePlay-USB-Companion.exe` inside the extracted folder. Keep its `_internal` folder alongside it. The preview is unsigned and Windows may display a warning.
- **macOS:** Unzip, move `rePlay-USB-Companion.app` to Applications, and open it. This preview is not Developer ID signed or notarized. If blocked, use the app-specific **Open Anyway** option in System Settings → Privacy & Security only after checking that it came from this release. Do not disable Gatekeeper globally.
- **Linux:** Extract the tar.gz in your file manager and open the `rePlay-USB-Companion` executable inside the extracted folder. Keep `_internal` alongside it. If necessary, enable **Allow executing file as program** in file properties. A graphical X11/XWayland session is required; distributions older than the listed glibc baseline and Alpine/musl are not supported.

No native Windows ARM64, iOS, Android or ChromeOS package is provided. Windows ARM64 may run the x64 build through Windows emulation, but that path has not been validated. Live tablet access and browser local-network permissions need validation on each target; CI startup checks do not establish those.

## Use

1. Open the extracted companion for your platform (see above).
2. In rePlay, select the **Tablet · USB** notebook source and select **Use the optional USB companion**.
3. Copy the displayed site origin into the companion's **Allow this rePlay site** field. Use the exact HTTPS origin for a hosted site, or the displayed localhost origin for the local app. No paths or wildcard origins are accepted.
4. Click **Start USB access**, then **Copy connection key**. Paste the key into rePlay and click **Connect companion**.
5. Enable the tablet's USB web interface under Storage. Browse folders and import a notebook. Keep the companion window open. Stop or close it to stop new requests; an already-running download may finish.

The browser may ask for local-network/loopback permission. Browser support varies; never disable browser security protections. A connection failure does not prevent cloud pairing or importing an existing file. Chrome's [local-network access documentation](https://developer.chrome.com/docs/modern-web-guidance/guides/security/local-network-access) describes this permission boundary.

The current bridge imports raw ink only. Text-anchored pages may need a matching PDF attached separately. The local app's existing direct USB backend retains its paired PDF workflow. Imported bytes go through the existing file-import consumer: in the current local app that saves the notebook on this computer. The standalone client module returns bytes to its caller and does not upload them to a hosted server.

## Tablet gallery previews

Companion v0.3.0 adds native PNG previews, requested serially only for visible notebook cards. The tablet may return the last-opened page rather than page 1, or no usable thumbnail. The UI shows a placeholder on failure; imports still work. Older companions remain compatible but do not provide previews. Requests are bounded to 4 MiB, five seconds of upstream socket timeout, and limited PNG dimensions. No whole notebook download is performed for a preview.

Connection setup collapses after a successful listing; use Connection settings to reopen it, or Disconnect to clear the session and previews.

## Troubleshooting

- Keep the companion running; check the allowed origin matches the website exactly (`https://replay.domj.net` for the public app).
- Restarting USB access generates a new key. Copy it again and reconnect in the browser.
- If prompted, allow the browser to access the local network. A browser that blocks loopback access may not support this flow; do not disable browser security.
- Check the USB cable supports data and that the tablet’s USB web interface is enabled. Stop other companion instances if port 8786 is already in use.
- Cloud pairing and file import remain available without the companion.

## Security and lifecycle

- Binds only `127.0.0.1:8786`; validates Host against that exact address/port to reject DNS rebinding.
- Allows one explicitly entered origin, echoed exactly in CORS. No wildcard, cookies or credentials-in-URLs.
- Every read requires a fresh 256-bit random connection key. Keys exist only in companion/browser memory and are regenerated on Start. The Copy button uses the clipboard; avoid pasting the key elsewhere.
- Only authenticated `GET /status`, `/documents?folder=UUID` , `/notebook?id=UUID` and optional `/thumbnail?id=UUID` exist. Preflight advertises only GET and the key header. No filesystem, arbitrary URL, device-write, SSH or remote command endpoints.
- Reuses the fixed `10.11.99.1` reader, rejects redirects, bypasses system proxies, bounds response/archive size and serializes USB work. A raw import compares member hashes from two reads. No raw files, cloud credentials or pairing data are persisted by the bridge.
- Closing/disconnecting the browser aborts client requests. Stop closes the listener; active tablet reads have bounded transport timeouts. Requests do not extend the listener beyond the visible desktop app lifetime.
- This is an unsigned development build, not a signed installer or a background service. macOS builds are not Developer ID signed or notarized.

## Developer build and validation

The `.github/workflows/companion.yml` workflow builds on each native target with Python 3.13 and PyInstaller 6.22.0, runs companion tests, then checks the packaged GUI remains running. `scripts/package-companion.py --platform <target>` performs the build, archive and checksum steps. Linux CI uses Xvfb for the startup check.

The older single-file Windows build remains available via `scripts/build-usb-companion.ps1` (build machine needs uv). Output stays under ignored `artifacts/usb-companion/dist/`. PyInstaller is build-only; it is not a dependency of the web app. See [PyInstaller windowed packaging](https://www.pyinstaller.org/en/latest/usage.html).

Tests use synthetic USB readers for origin/key/Host rejection, preflight, read-only routes and stable-capture dispatch. Browser-client tests verify no contact before opt-in, fixed loopback routing, credential omission, disconnect, failures and invalid archives. Live tablet reachability and browser permission support are separate checks, not implied by these tests.
