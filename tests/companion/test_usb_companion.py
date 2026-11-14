import http.client
import threading
from types import SimpleNamespace

import pytest

from rm_redraw.companion.server import create_server, validate_origin

ORIGIN = "https://replay.example"
DOC = "12345678-1234-1234-1234-123456789abc"


@pytest.fixture
def bridge():
    calls = []
    reader = SimpleNamespace(
        documents=lambda folder: calls.append(("list", folder)) or [],
        capture=lambda doc, **kw: (calls.append(("capture", doc, kw)) or b"zip", None, {}),
    )
    server = create_server(ORIGIN, reader=reader, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, calls
    server.shutdown()
    server.server_close()
    thread.join()


def request(bridge, path="/status", *, origin=ORIGIN, token=True, method="GET", extra=None):
    server, _ = bridge
    headers = {"Origin": origin}
    if token:
        headers["X-Replay-USB-Token"] = server.token
    headers.update(extra or {})
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    conn.request(method, path, headers=headers)
    response = conn.getresponse()
    result = response.status, dict(response.getheaders()), response.read()
    conn.close()
    return result


def test_auth_origin_host_and_no_writes(bridge):
    for args in (
        {"token": False},
        {"origin": "https://evil.example"},
        {"origin": "null"},
        {"extra": {"Host": "evil.example"}},
    ):
        assert request(bridge, "/documents", **args)[0] == 403
    assert request(bridge, "/documents", method="POST")[0] == 405
    assert bridge[1] == []
    status, headers, _ = request(bridge)
    assert status == 200
    assert headers["Access-Control-Allow-Origin"] == ORIGIN
    assert headers["Cache-Control"] == "no-store"


def test_preflight_only_permits_exact_site_and_headers(bridge):
    headers = {
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "x-replay-usb-token",
        "Access-Control-Request-Private-Network": "true",
    }
    status, response, _ = request(bridge, token=False, method="OPTIONS", extra=headers)
    assert status == 204
    assert response["Access-Control-Allow-Private-Network"] == "true"
    assert (
        request(
            bridge,
            token=False,
            method="OPTIONS",
            extra={**headers, "Access-Control-Request-Method": "POST"},
        )[0]
        == 403
    )
    assert (
        request(
            bridge, token=False, method="OPTIONS", origin="https://evil.example", extra=headers
        )[0]
        == 403
    )


def test_only_fixed_read_routes_and_stable_capture(bridge):
    assert request(bridge, "/documents")[0] == 200
    assert request(bridge, "/notebook?id=" + DOC)[2] == b"zip"
    assert bridge[1] == [("list", ""), ("capture", DOC, {"include_pdf": False})]
    assert request(bridge, "/notebook?id=../../bad")[0] == 400
    assert request(bridge, "/fetch?url=http://evil.example")[0] == 404
    assert request(bridge, "/documents?folder=" + DOC + "&folder=" + DOC)[0] == 400


def test_origin_must_be_one_secure_site_or_local_dev_origin():
    for value in [
        "*",
        "null",
        "http://example.com",
        "https://user:pass@example.com",
        "https://example.com/path",
        "https://example.com?x=1",
    ]:
        with pytest.raises(ValueError):
            validate_origin(value)
    assert validate_origin(ORIGIN) == ORIGIN
    assert validate_origin("http://127.0.0.1:8765") == "http://127.0.0.1:8765"


def test_busy_bridge_rejects_before_tablet_access(bridge):
    server, calls = bridge
    server.slot.acquire()
    try:
        assert request(bridge, "/documents")[0] == 409
        assert calls == []
    finally:
        server.slot.release()
    assert request(bridge, "/documents", extra={"X-Replay-USB-Token": "wrong"})[0] == 403
    assert calls == []


def test_thumbnail_route_is_authenticated_and_validates_id(bridge):
    bridge[0].reader.thumbnail = lambda doc: b"png-test"
    assert request(bridge, "/thumbnail?id=" + DOC)[2] == b"png-test"
    assert request(bridge, "/thumbnail?id=" + DOC, token=False)[0] == 403
    assert request(bridge, "/thumbnail?id=../bad")[0] == 400


def test_usb_thumbnail_is_bounded_png():
    import struct

    from rm_redraw.acquisition.usb import UsbReader

    reader = UsbReader()
    png = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 384, 512)
    reader._get = lambda route, **kwargs: png
    assert reader.thumbnail(DOC) == png
    with pytest.raises(ValueError):
        reader.thumbnail("../bad")
    reader._get = lambda route, **kwargs: b"not an image"
    with pytest.raises(ValueError):
        reader.thumbnail(DOC)
    reader._get = lambda route, **kwargs: png[:16] + struct.pack(">II", 100000, 100000)
    with pytest.raises(ValueError):
        reader.thumbnail(DOC)
