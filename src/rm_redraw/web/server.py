"""Loopback-only HTTP UI. No tablet writes or arbitrary-path/URL endpoints."""

import json
import mimetypes
import secrets
import shutil
import threading
from dataclasses import asdict
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from rm_redraw.acquisition.cloud import CloudError
from rm_redraw.acquisition.cloud_relay import CloudRelay, CloudRelayError
from rm_redraw.acquisition.usb import UsbReader

from .jobs import CanvasClippingError, Jobs, page_info
from .library import MAX_BYTES, Library
from .previews import Previews

ASSETS = Path(__file__).with_name("static")


class App:
    def __init__(self, root):
        self.root = root
        self.token = secrets.token_urlsafe(32)
        self.library = Library(root / "library")
        self.jobs = Jobs(root / "jobs", self.library)
        self.previews = Previews(root / "previews", self.library, self.jobs.executor)
        self.usb = UsbReader()
        # Historical adapter remains injectable for compatibility tests only.
        # Normal app startup neither discovers nor launches a CLI companion.
        self.cloud = None
        self.cloud_relay = CloudRelay()
        self.relay_slots = threading.BoundedSemaphore(2)
        self.import_lock = threading.Lock()

    def capabilities(self):
        try:
            from rm_redraw.rendering.native_pencil import native_info

            native_info()
            rust = True
        except (RuntimeError, OSError):
            rust = False
        return {
            "token": self.token,
            "rust": rust,
            "ffmpeg": bool(shutil.which("ffmpeg")),
            "poppler": bool(shutil.which("pdftoppm")),
        }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    @property
    def app(self):
        return self.server.app

    def _trusted(self):
        expected = f"127.0.0.1:{self.server.server_port}"
        return (
            self.headers.get("Host") == expected
            and self.headers.get("Origin", "http://" + expected) == "http://" + expected
            and self.headers.get("Sec-Fetch-Site", "none") != "cross-site"
        )

    def _authenticated(self):
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        value = cookie.get("replay_session")
        return value is not None and secrets.compare_digest(value.value, self.app.token)

    def _headers(self, code, kind, length, *, cookie=False, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; connect-src 'self' http://127.0.0.1:8786; "
            "img-src 'self' blob:; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )
        if cookie:
            self.send_header(
                "Set-Cookie", f"replay_session={self.app.token}; HttpOnly; SameSite=Strict; Path=/"
            )
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()

    def _json(self, data, code=200):
        body = json.dumps(data).encode()
        self._headers(code, "application/json", len(body))
        self.wfile.write(body)

    def _file(self, path, *, cookie=False):
        size = path.stat().st_size
        start, end, code = 0, size - 1, 200
        extra = {"Accept-Ranges": "bytes"}
        requested = self.headers.get("Range")
        if requested:
            try:
                if not requested.startswith("bytes=") or "," in requested:
                    raise ValueError()
                left, right = requested[6:].split("-")
                start = int(left) if left else max(0, size - int(right))
                end = min(size - 1, int(right)) if left and right else size - 1
                if not 0 <= start <= end < size:
                    raise ValueError()
            except ValueError:
                self._headers(416, "text/plain", 0, extra={"Content-Range": f"bytes */{size}"})
                return
            code = 206
            extra["Content-Range"] = f"bytes {start}-{end}/{size}"
        self._headers(
            code,
            "text/javascript; charset=utf-8"
            if path.suffix in (".js", ".mjs")
            else mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            end - start + 1,
            cookie=cookie,
            extra=extra,
        )
        if self.command == "HEAD":
            return
        with path.open("rb") as source:
            source.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = source.read(min(65536, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            if not self._trusted():
                self._json({"error": "Only this local origin is allowed"}, 403)
                return
            url = urlsplit(self.path)
            if url.path in (
                "/",
                "/app.js",
                "/style.css",
                "/cloud-ui.mjs",
                "/cloud-client.mjs",
                "/cloud-vault.mjs",
                "/usb-companion.mjs",
            ):
                name = "index.html" if url.path == "/" else url.path[1:]
                self._file(ASSETS / name, cookie=url.path == "/")
                return
            if not self._authenticated():
                self._json({"error": "Open the utility home page first"}, 403)
                return
            query = parse_qs(url.query)
            if url.path == "/api/session":
                self._json(self.app.capabilities())
            elif url.path == "/api/library":
                self._json(self.app.library.list())
            elif url.path == "/api/jobs":
                self._json(self.app.jobs.list())
            elif url.path == "/api/page-preview":
                self._json(self.app.previews.get(query["id"][0]))
            elif url.path.startswith("/page-previews/") and url.path.endswith(".png"):
                self._file(self.app.previews.image(url.path.removeprefix("/page-previews/")[:-4]))
            elif url.path == "/api/page":
                info, _ = page_info(self.app.library, query["document"][0], query["page"][0])
                self._json(info)
            elif url.path == "/api/cloud-status":
                self._json(
                    self.app.cloud.status() if self.app.cloud else {"state": "browser-managed"}
                )
            elif url.path == "/api/usb":
                self._json(self.app.usb.documents(query.get("folder", [""])[0]))
            elif url.path.startswith("/media/"):
                parts = url.path.split("/")
                if len(parts) != 4:
                    raise FileNotFoundError()
                self._file(self.app.jobs.media(parts[2], parts[3]))
            else:
                raise FileNotFoundError()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except FileNotFoundError:
            self._json({"error": "Not found"}, 404)
        except Exception as error:
            self._json({"error": str(error)}, 400)

    def do_POST(self):
        importing = False
        relaying = False
        cloud_account = False
        try:
            if (
                not self._trusted()
                or not self._authenticated()
                or not secrets.compare_digest(
                    self.headers.get("X-Replay-Token", ""), self.app.token
                )
            ):
                self._json({"error": "Local session required"}, 403)
                return
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("Chunked requests are not supported")
            url = urlsplit(self.path)
            if url.path == "/api/cloud-relay":
                relaying = self.app.relay_slots.acquire(blocking=False)
                if not relaying:
                    self._json({"error": "Cloud relay is busy; retry shortly"}, 503)
                    return
            if self.app.cloud is None and url.path in (
                "/api/cloud-pair",
                "/api/cloud-revoke",
                "/api/cloud-list",
                "/api/cloud-import",
            ):
                self._json({"error": "Use browser pairing; the CLI connector is retired"}, 410)
                return
            cloud_account = url.path in ("/api/cloud-pair", "/api/cloud-revoke")
            upload = url.path in ("/api/upload", "/api/upload-pdf")
            limit = MAX_BYTES if upload else (32768 if relaying else 16384)
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
                raise ValueError("A valid Content-Length is required")
            length = int(lengths[0])
            if length == 0:
                raise ValueError("Request is empty")
            if length > limit:
                maximum = "128 MiB" if upload else ("32 KiB" if relaying else "16 KiB")
                self._json({"error": f"Request exceeds the {maximum} limit"}, 413)
                return
            expected = "application/octet-stream" if upload else "application/json"
            if self.headers.get_content_type() != expected:
                self._json({"error": f"Expected {expected}"}, 415)
                return
            if upload or url.path in ("/api/usb-import", "/api/cloud-import"):
                importing = self.app.import_lock.acquire(blocking=False)
                if not importing:
                    self._json({"error": "Another import is already in progress"}, 409)
                    return
            self.connection.settimeout(120)
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("Incomplete upload")
            if upload:
                if url.path == "/api/upload":
                    result = self.app.library.add(body, provenance={"provider": "browser-upload"})
                else:
                    document_id = parse_qs(url.query)["document"][0]
                    record = self.app.library.get(document_id)
                    result = self.app.library.add(
                        self.app.library.source(document_id).read_bytes(),
                        provenance={
                            "provider": "browser-paired-pdf",
                            "source": record["id"],
                            "pairing": "user-supplied PDF; page count checked",
                        },
                        pdf=body,
                    )
            else:
                data = json.loads(body)
                if not isinstance(data, dict):
                    raise ValueError("Expected a JSON object")
                if url.path == "/api/cloud-relay":
                    try:
                        response, kind = self.app.cloud_relay.request(data)
                    except CloudRelayError as error:
                        self._json({"error": str(error)}, error.status)
                    except Exception:
                        self._json({"error": "Cloud relay failed"}, 502)
                    else:
                        self._headers(200, kind, len(response))
                        self.wfile.write(response)
                    return
                if url.path == "/api/usb-import":
                    if type(data.get("pdf")) is not bool:
                        raise ValueError("pdf must be true or false")
                    raw, pdf, provenance = self.app.usb.capture(
                        data["id"],
                        include_pdf=data["pdf"],
                        attempt_directory=self.app.root / "import-attempts" / uuid4().hex,
                    )
                    result = self.app.library.add(raw, provenance=provenance, pdf=pdf)
                elif url.path == "/api/cloud-list":
                    result = [asdict(item) for item in self.app.cloud.list_documents()]
                elif url.path == "/api/cloud-pair":
                    if not isinstance(data.get("code"), str):
                        self._json({"error": "Enter a pairing code"}, 400)
                        return
                    self.app.cloud.pair(data["code"])
                    result = {"paired": True}
                elif url.path == "/api/cloud-revoke":
                    self.app.cloud.revoke()
                    result = {"revoked": True}
                elif url.path == "/api/cloud-import":
                    raw = self.app.cloud.download_archive(data["id"])
                    result = self.app.library.add(
                        raw,
                        provenance={
                            "provider": "rmctl-cloud",
                            "source_document_id": data["id"],
                            "pairing": "user-managed local rmctl profile; unofficial cloud API",
                            "reference": "raw-only cloud archive; no paired native PDF",
                        },
                    )
                elif url.path == "/api/jobs":
                    result = self.app.jobs.submit(data["document"], data["page"], data["settings"])
                elif url.path == "/api/page-preview":
                    result = self.app.previews.submit(
                        data["document"], data["page"], data["settings"]
                    )
                elif url.path == "/api/export":
                    result = self.app.jobs.submit_export(
                        data["job"], data.get("crop"), data.get("reverse_speed", 0)
                    )
                elif url.path == "/api/cancel":
                    self.app.jobs.cancel(data["id"])
                    result = {"cancelled": True}
                else:
                    self._json({"error": "Not found"}, 404)
                    return
            self._json(result)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except CanvasClippingError as error:
            self._json({"error": str(error), "code": "canvas_clipping"}, 422)
        except Exception as error:
            message = (
                "Cloud account action failed. Check the local companion."
                if cloud_account and not isinstance(error, CloudError)
                else str(error)
            )
            self._json({"error": message}, 400)
        finally:
            if relaying:
                self.app.relay_slots.release()
            if importing:
                self.app.import_lock.release()


def create_server(root: Path, *, port=8765):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.app = App(root.resolve())
    return server
