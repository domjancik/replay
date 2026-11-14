"""Origin-bound loopback bridge; fixed tablet routes, no proxy or device writes."""

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from rm_redraw.acquisition.source import UUID_RE
from rm_redraw.acquisition.usb import UsbReader

PORT = 8786


def validate_origin(value):
    value = value.strip()
    url = urlsplit(value)
    try:
        _ = url.port
    except ValueError as error:
        raise ValueError("Invalid site port") from error
    local = url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1")
    if (
        not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path
        or (url.scheme != "https" and not local)
        or any(c.isspace() for c in value)
        or "*" in value
    ):
        raise ValueError("Enter one HTTPS site origin, without a path, or http://127.0.0.1:8765")
    return value


class BridgeHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args):
        pass  # Never log credentials, document identifiers or tablet responses.

    def trusted(self):
        return (
            self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"
            and self.headers.get("Origin") == self.server.origin
        )

    def reply(self, code, body=b"", kind="application/json", *, preflight=False):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Vary", "Origin")
        if self.trusted():
            self.send_header("Access-Control-Allow-Origin", self.server.origin)
            if preflight:
                self.send_header("Access-Control-Allow-Methods", "GET")
                self.send_header("Access-Control-Allow-Headers", "X-Replay-USB-Token")
                self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()
        self.wfile.write(body)

    def error(self, code, message):
        self.reply(code, json.dumps({"error": message}).encode())

    def do_OPTIONS(self):
        headers = {
            s.strip().lower()
            for s in self.headers.get("Access-Control-Request-Headers", "").split(",")
            if s.strip()
        }
        if (
            not self.trusted()
            or self.headers.get("Access-Control-Request-Method") != "GET"
            or not headers.issubset({"x-replay-usb-token"})
        ):
            self.error(403, "Site or request not allowed")
            return
        self.reply(204, preflight=True)

    def do_POST(self):
        self.error(405, "This companion only reads from the tablet")

    do_PUT = do_DELETE = do_PATCH = do_POST

    def do_GET(self):
        supplied = self.headers.get("X-Replay-USB-Token", "")
        if not self.trusted() or not secrets.compare_digest(
            supplied.encode(), self.server.token.encode()
        ):
            self.error(403, "Check the allowed site and connection key in the companion")
            return
        if not self.server.slot.acquire(blocking=False):
            self.error(409, "USB is busy. Wait for the current operation to finish.")
            return
        try:
            url = urlsplit(self.path)
            query = parse_qs(url.query, keep_blank_values=True, max_num_fields=4)
            if any(len(values) != 1 for values in query.values()):
                raise ValueError("Duplicate query parameters")
            if url.path == "/status" and not query:
                self.reply(200, b'{"version":1,"read_only":true,"thumbnails":true}')
            elif url.path == "/documents" and set(query).issubset({"folder"}):
                folder = query.get("folder", [""])[0]
                if folder and not UUID_RE.fullmatch(folder):
                    raise ValueError("Invalid folder ID")
                self.server.report("Reading tablet folders…")
                self.reply(200, json.dumps(self.server.reader.documents(folder)).encode())
            elif url.path == "/thumbnail" and set(query) == {"id"}:
                document = query["id"][0]
                if not UUID_RE.fullmatch(document):
                    raise ValueError("Invalid notebook ID")
                self.reply(200, self.server.reader.thumbnail(document), "image/png")
            elif url.path == "/notebook" and set(query) == {"id"}:
                document = query["id"][0]
                if not UUID_RE.fullmatch(document):
                    raise ValueError("Invalid notebook ID")
                self.server.report("Downloading notebook; verifying two raw reads…")
                raw, _, _ = self.server.reader.capture(document, include_pdf=False)
                self.reply(200, raw, "application/octet-stream")
            else:
                self.error(404, "Unknown read-only operation")
        except ValueError as error:
            self.error(400, str(error))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.error(502, "Tablet unavailable. Check USB and enable its USB web interface.")
        finally:
            self.server.slot.release()
            self.server.report("Ready. Read-only USB access enabled.")


def create_server(origin, *, reader=None, port=PORT, report=lambda _: None):
    origin = validate_origin(origin)
    server = ThreadingHTTPServer(("127.0.0.1", port), BridgeHandler)
    server.daemon_threads = True
    server.origin = origin
    server.token = secrets.token_urlsafe(32)
    server.reader = reader or UsbReader()
    server.slot = threading.Lock()
    server.report = report
    return server
