# Optional USB companion

Cloud pairing and file import do not use this companion. It is a small, separate desktop app for allowing a browser to read a USB-connected tablet. The Windows build bundles Python and Tk; end users do not need a terminal, Python, uv, FFmpeg or a renderer installation.

## Download

[Download for Windows x64](https://github.com/domjancik/replay/releases/download/companion-v0.1.0/rePlay-USB-Companion.exe) · [Release notes and SHA-256 checksum](https://github.com/domjancik/replay/releases/tag/companion-v0.1.0)

Portable unsigned preview: Windows may display a security warning. No installer, administrator access or terminal is required. macOS/Linux downloads are not available yet. Download only from the linked project release.

## Use

1. Open `rePlay-USB-Companion.exe`.
2. In rePlay, select the **Tablet · USB** notebook source and select **Use the optional USB companion**.
3. Copy the displayed site origin into the companion's **Allow this rePlay site** field. Use the exact HTTPS origin for a hosted site, or the displayed localhost origin for the local app. No paths or wildcard origins are accepted.
4. Click **Start USB access**, then **Copy connection key**. Paste the key into rePlay and click **Connect companion**.
5. Enable the tablet's USB web interface under Storage. Browse folders and import a notebook. Keep the companion window open. Stop or close it to stop new requests; an already-running download may finish.

The browser may ask for local-network/loopback permission. Browser support varies; never disable browser security protections. A connection failure does not prevent cloud pairing or importing an existing file. Chrome's [local-network access documentation](https://developer.chrome.com/docs/modern-web-guidance/guides/security/local-network-access) describes this permission boundary.

The current bridge imports raw ink only. Text-anchored pages may need a matching PDF attached separately. The local app's existing direct USB backend retains its paired PDF workflow. Imported bytes go through the existing file-import consumer: in the current local app that saves the notebook on this computer. The standalone client module returns bytes to its caller and does not upload them to a hosted server.

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
- Only authenticated `GET /status`, `/documents?folder=UUID` and `/notebook?id=UUID` exist. Preflight advertises only GET and the key header. No filesystem, arbitrary URL, device-write, SSH or remote command endpoints.
- Reuses the fixed `10.11.99.1` reader, rejects redirects, bypasses system proxies, bounds response/archive size and serializes USB work. A raw import compares member hashes from two reads. No raw files, cloud credentials or pairing data are persisted by the bridge.
- Closing/disconnecting the browser aborts client requests. Stop closes the listener; active tablet reads have bounded transport timeouts. Requests do not extend the listener beyond the visible desktop app lifetime.
- This is an unsigned development build, not a signed installer or a background service. macOS packaging/signing has not been validated.

## Developer build and validation

Run `scripts/build-usb-companion.ps1` on Windows (build machine needs uv). Output stays under ignored `artifacts/usb-companion/dist/`. PyInstaller is build-only; it is not a dependency of the web app. See [PyInstaller windowed packaging](https://www.pyinstaller.org/en/latest/usage.html).

Tests use synthetic USB readers for origin/key/Host rejection, preflight, read-only routes and stable-capture dispatch. Browser-client tests verify no contact before opt-in, fixed loopback routing, credential omission, disconnect, failures and invalid archives. Live tablet reachability and browser permission support are separate checks, not implied by these tests.
