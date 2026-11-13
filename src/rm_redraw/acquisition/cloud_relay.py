"""Bounded, stateless transport for browser-owned reMarkable Cloud sessions."""

import base64
import hashlib
import http.client
import json
import re
import socket
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .archive import MAX_BYTES

_AUTH = "https://webapp-prod.cloud.remarkable.engineering"
_SYNC = "https://internal.cloud.remarkable.com"
_TIMEOUT = 15
_BODY_DEADLINE = 60
_TOKEN_LIMIT = 16 * 1024
_ROOT_LIMIT = 1024 * 1024
_INDEX_LIMIT = 16 * 1024 * 1024
_HASH = re.compile(r"[0-9a-f]{64}")
_TOKEN = re.compile(r"[A-Za-z0-9._~+/=-]+")
_CODE = re.compile(r"[A-Za-z0-9]{8}")
_DEVICE_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
_FILENAME = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*")
_REGION = re.compile(r"[a-z]{2,8}")
_FIELDS = {
    "pair": {"action", "code", "device_id"},
    "session": {"action", "token"},
    "root": {"action", "token"},
    "file": {"action", "token", "hash", "filename"},
    "revoke": {"action", "token"},
}


class CloudRelayError(RuntimeError):
    """A safe client-facing failure with an HTTP status."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


class _UnreachableHost(CloudRelayError):
    def __init__(self):
        super().__init__("Could not connect to the reMarkable Cloud.", 502)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _valid_token(value: object) -> bool:
    return isinstance(value, str) and len(value) <= _TOKEN_LIMIT and bool(_TOKEN.fullmatch(value))


def _sync_host(token: str) -> str:
    # This unverified JWT claim is routing advice only. Its restricted form can
    # select one first-party DNS label and cannot change scheme, domain or port.
    segments = token.split(".")
    if len(segments) == 3:
        try:
            claims = json.loads(
                base64.urlsafe_b64decode(segments[1] + "=" * (-len(segments[1]) % 4))
            )
            region = claims.get("tectonic") if isinstance(claims, dict) else None
        except (ValueError, RecursionError):
            region = None
        if isinstance(region, str) and _REGION.fullmatch(region.lower()):
            return f"https://{region.lower()}.tectonic.remarkable.com"
    return _SYNC


def _file_fields(payload: dict) -> tuple[str, str]:
    digest, filename = payload["hash"], payload["filename"]
    if not isinstance(digest, str) or not _HASH.fullmatch(digest):
        raise CloudRelayError("Invalid cloud file hash.", 400)
    if (
        not isinstance(filename, str)
        or len(filename) > 255
        or not _FILENAME.fullmatch(filename)
        or any(part in (".", "..") for part in filename.split("/"))
    ):
        raise CloudRelayError("Invalid cloud file name.", 400)
    return digest, filename


class CloudRelay:
    """Relay only the fixed cloud operations needed by the browser notebook picker."""

    def __init__(self):
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())
        self._opener.addheaders = []
        self._slots = threading.BoundedSemaphore(4)

    def request(self, payload: object) -> tuple[bytes, str]:
        if not isinstance(payload, dict):
            raise CloudRelayError("Expected a cloud request object.", 400)
        action = payload.get("action")
        if (
            not isinstance(action, str)
            or action not in _FIELDS
            or payload.keys() != _FIELDS[action]
        ):
            raise CloudRelayError("Invalid cloud request fields.", 400)
        if action != "pair" and not _valid_token(payload["token"]):
            raise CloudRelayError("Invalid cloud session token.", 400)

        if not self._slots.acquire(blocking=False):
            raise CloudRelayError("The cloud connection is busy. Retry in a moment.", 503)
        try:
            return self._dispatch(action, payload)
        finally:
            self._slots.release()

    def _dispatch(self, action: str, payload: dict) -> tuple[bytes, str]:
        if action == "pair":
            return self._pair(payload)
        token = payload["token"]
        authorization = {"Authorization": "Bearer " + token}
        if action == "session":
            request = Request(
                _AUTH + "/token/json/2/user/new", headers=authorization, method="POST"
            )
            return self._read_token(request, action)
        if action == "revoke":
            request = Request(
                _AUTH + "/token/json/3/device/delete", headers=authorization, method="POST"
            )
            status, _ = self._send(request, _TOKEN_LIMIT)
            if status not in (401, 403):
                _require_success(status, action)
            return b"{}", "application/json"

        sync = _sync_host(token)
        if action == "root":
            return self._root(sync, authorization)
        digest, filename = _file_fields(payload)
        status, data = self._send_sync(
            sync,
            f"/sync/v3/files/{digest}",
            {**authorization, "rm-filename": filename},
            _INDEX_LIMIT if filename.endswith(".docSchema") else MAX_BYTES,
        )
        _require_success(status, action)
        # Index addresses can be node hashes. The browser verifies both index
        # encodings, while immutable file bytes always use their direct hash.
        if not filename.endswith(".docSchema") and hashlib.sha256(data).hexdigest() != digest:
            raise CloudRelayError("The cloud file did not match its expected hash.", 502)
        return data, "application/octet-stream"

    def _pair(self, payload: dict) -> tuple[bytes, str]:
        code, device_id = payload["code"], payload["device_id"]
        if not isinstance(code, str) or not _CODE.fullmatch(code.strip()):
            raise CloudRelayError("Enter the eight letters or digits in the pairing code.", 400)
        if not isinstance(device_id, str) or not _DEVICE_ID.fullmatch(device_id.lower()):
            raise CloudRelayError("Invalid cloud device identifier.", 400)
        request = Request(
            _AUTH + "/token/json/2/device/new",
            json.dumps(
                {
                    "code": code.strip().lower(),
                    "deviceDesc": "desktop-macos",
                    "deviceID": device_id.lower(),
                },
                separators=(",", ":"),
            ).encode(),
            {"Content-Type": "application/json"},
        )
        return self._read_token(request, "pair")

    def _read_token(self, request: Request, action: str) -> tuple[bytes, str]:
        status, data = self._send(request, _TOKEN_LIMIT)
        _require_success(status, action)
        try:
            token = data.decode("utf-8").strip()
        except UnicodeDecodeError:
            token = None
        if not _valid_token(token):
            raise CloudRelayError("The cloud returned an invalid token.", 502)
        return token.encode("ascii"), "text/plain; charset=utf-8"

    def _root(self, sync: str, headers: dict) -> tuple[bytes, str]:
        headers = {**headers, "rm-filename": "roothash"}
        status, data = self._send_sync(sync, "/sync/v4/root", headers, _ROOT_LIMIT)
        if status == 404:
            status, data = self._send_sync(sync, "/sync/v3/root", headers, _ROOT_LIMIT)
        _require_success(status, "root")
        try:
            record = json.loads(data)
        except (ValueError, RecursionError):
            record = None
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("hash"), str)
            or not _HASH.fullmatch(record["hash"])
            or type(record.get("generation")) is not int
        ):
            raise CloudRelayError("The cloud returned an invalid library root.", 502)
        return data, "application/json"

    def _send_sync(self, host: str, path: str, headers: dict, limit: int) -> tuple[int, bytes]:
        try:
            return self._send(Request(host + path, headers=headers), limit)
        except _UnreachableHost:
            if host == _SYNC:
                raise
            return self._send(Request(_SYNC + path, headers=headers), limit)

    def _send(self, request: Request, limit: int) -> tuple[int, bytes]:
        deadline = time.monotonic() + _BODY_DEADLINE
        try:
            with self._opener.open(request, timeout=_TIMEOUT) as response:
                if not 200 <= response.status < 300:
                    return response.status, b""
                return response.status, _read_bounded(response, limit, deadline)
        except HTTPError as error:
            error.close()
            return error.code, b""
        except TimeoutError:
            raise CloudRelayError("The cloud request timed out.", 504) from None
        except URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise CloudRelayError("The cloud request timed out.", 504) from None
            if isinstance(error.reason, (socket.gaierror, ConnectionRefusedError)):
                raise _UnreachableHost() from None
            raise CloudRelayError("Could not connect to the reMarkable Cloud.", 502) from None
        except (OSError, http.client.HTTPException):
            raise CloudRelayError("Could not read the reMarkable Cloud response.", 502) from None


def _read_bounded(response, limit: int, deadline: float) -> bytes:
    declared = response.headers.get("Content-Length")
    if declared is not None:
        if not declared.isascii() or not declared.isdecimal() or len(declared) > 12:
            raise CloudRelayError("The cloud returned an invalid response length.", 502)
        if int(declared) > limit:
            raise CloudRelayError("The cloud response exceeds the size limit.", 502)
    body = bytearray()
    while len(body) <= limit:
        if time.monotonic() >= deadline:
            raise CloudRelayError("The cloud request timed out.", 504)
        block = response.read1(min(64 * 1024, limit + 1 - len(body)))
        if not block:
            if declared is not None and int(declared) != len(body):
                raise CloudRelayError("The cloud response was incomplete.", 502)
            return bytes(body)
        body.extend(block)
    raise CloudRelayError("The cloud response exceeds the size limit.", 502)


def _require_success(status: int, action: str) -> None:
    if 200 <= status < 300:
        return
    if action == "pair" and status in (400, 401, 403):
        raise CloudRelayError("The cloud rejected the pairing code. Generate a new code.", 400)
    messages = {
        401: "The cloud session was rejected.",
        402: "This cloud action is unavailable on the account's plan.",
        403: "The cloud session is not authorized for this action.",
        404: "The cloud library or requested file is unavailable.",
        429: "The cloud is rate-limiting requests. Retry in a moment.",
    }
    if status in messages:
        raise CloudRelayError(messages[status], status)
    if action == "session" and status == 400:
        raise CloudRelayError("The account could not open a cloud session.", 400)
    raise CloudRelayError("The reMarkable Cloud returned an unexpected response.", 502)
