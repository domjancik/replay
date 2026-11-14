"""Build a code-only Vercel staging directory. Never includes user fixtures."""

import json
import shutil
from pathlib import Path

root = Path(__file__).resolve().parents[2]
out = root / "artifacts/hosted-replay"
public = out / "public"
public.mkdir(parents=True, exist_ok=True)
for name in [
    "index.html",
    "style.css",
    "app.js",
    "cloud-client.mjs",
    "cloud-ui.mjs",
    "cloud-vault.mjs",
    "usb-companion.mjs",
]:
    shutil.copyfile(root / "src/rm_redraw/web/static" / name, public / name)
html = (
    (public / "index.html")
    .read_text(encoding="utf8")
    .replace(
        '<script defer src="/app.js"></script>',
        '<script type="module" src="/bootstrap.mjs"></script>',
    )
)
html = html.replace("On this computer", "In this browser").replace(
    "Your original notebook stays untouched.",
    "Rendering runs on your device. Keep this tab open while jobs run.",
)
html = html.replace(
    "Closing this dialog locks the vault.", "Lock the vault when you finish."
).replace(
    "Text-anchored pages may need a separately attached matching PDF.",
    "Attach the matching native PDF for pages with text anchors; "
    "matching runs in Rust/WASM on this device.",
)
html = html.replace(
    "Downloaded ink feeds the same local replay engine.",
    (
        "Downloaded ink is parsed and rendered in this browser. Imported notebooks and generated "
        "videos are stored unencrypted in this browser’s local library; cloud pairing "
        "credentials use the protection option you selected."
    ),
)
html = html.replace(
    "No new ink rendering.", "Frames are rendered again on this device for the export."
)
(public / "index.html").write_text(html, encoding="utf8")
for name in [
    "bootstrap.mjs",
    "browser-api.mjs",
    "worker.mjs",
    "pdf-reference.mjs",
    "largeblob-check.html",
    "largeblob-check.mjs",
    "largeblob-probe.mjs",
]:
    shutil.copyfile(root / "native/hosted" / name, public / name)
shutil.copyfile(root / "native/renderer/renderer.mjs", public / "renderer.mjs")
shutil.copyfile(
    root / "native/renderer/target/wasm32-unknown-unknown/release/rm_renderer.wasm",
    public / "renderer.wasm",
)
shutil.copyfile(
    root / "artifacts/video-prototype-20261113/site/encoder.mjs", public / "encoder.mjs"
)
shutil.copyfile(
    root / "artifacts/video-prototype-20261113/site/MEDIABUNNY-LICENSE",
    public / "MEDIABUNNY-LICENSE",
)
shutil.copyfile(root / "native/renderer/LICENSE-PILLOW", public / "LICENSE-PILLOW")
for name in ["LICENSE", "THIRD_PARTY_NOTICES.md"]:
    shutil.copyfile(root / name, public / name)
shutil.copytree(root / "native/hosted/licenses", public / "licenses", dirs_exist_ok=True)
shutil.copyfile(root / "native/replay-core/core.mjs", public / "core.mjs")
shutil.copyfile(
    root / "native/replay-core/target/wasm32-unknown-unknown/release/rm_replay_core.wasm",
    public / "replay-core.wasm",
)
pdfjs = root / "artifacts/hosted-dependencies/node_modules/pdfjs-dist"
(public / "pdfjs").mkdir(exist_ok=True)
for name in ["pdf.mjs", "pdf.worker.mjs", "pdf.renderer.mjs"]:
    if (pdfjs / "build" / name).exists():
        shutil.copyfile(pdfjs / "build" / name, public / "pdfjs" / name)
for name in ["wasm", "standard_fonts", "cmaps"]:
    shutil.copytree(pdfjs / name, public / "pdfjs" / name, dirs_exist_ok=True)
shutil.copyfile(pdfjs / "LICENSE", public / "licenses/PDFJS-LICENSE")
# Remove only the previous generated Python runtime inside this staging directory.
runtime = public / "runtime"
if runtime.exists():
    if runtime.is_symlink() or runtime.resolve().parent != public.resolve():
        raise ValueError("Unsafe stale runtime path")
    shutil.rmtree(runtime)
(public / "licenses/PYODIDE-LICENSE").unlink(missing_ok=True)
shutil.copyfile(root / "native/rmdoc/reader.mjs", public / "reader.mjs")
shutil.copyfile(
    root / "native/rmdoc/target/wasm32-unknown-unknown/release/rm_rmdoc.wasm",
    public / "rmdoc.wasm",
)
shutil.copyfile(root / "native/rmdoc/LICENSE-RMSCENE", public / "licenses/RMSCENE-LICENSE")
(out / "api").mkdir(exist_ok=True)
shutil.copyfile(root / "native/hosted/api/cloud-relay.mjs", out / "api/cloud-relay.mjs")
config = {
    "version": 2,
    "outputDirectory": "public",
    "functions": {"api/cloud-relay.mjs": {"maxDuration": 60}},
    "headers": [
        {
            "source": "/(.*)",
            "headers": [
                {
                    "key": "Content-Security-Policy",
                    "value": (
                        "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; "
                        "worker-src 'self'; connect-src 'self' http://127.0.0.1:8786; "
                        "img-src 'self' blob: data:; media-src 'self' blob:; style-src 'self'; "
                        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
                    ),
                },
                {"key": "X-Content-Type-Options", "value": "nosniff"},
                {"key": "Referrer-Policy", "value": "no-referrer"},
                {"key": "Cache-Control", "value": "no-cache"},
            ],
        }
    ],
}
(out / "vercel.json").write_text(json.dumps(config, indent=2), encoding="utf8")
(out / "package.json").write_text(
    json.dumps({"private": True, "type": "module", "engines": {"node": "22.x"}}), encoding="utf8"
)
print(out)
