import json
import threading
from types import SimpleNamespace

from test_server import request, session

pytest_plugins = ("test_server",)


def test_relay_requires_session_and_never_persists_payload(server):
    calls = []

    def relay(payload):
        calls.append(payload["action"])
        return b"private-token", "text/plain; charset=utf-8"

    server.app.cloud_relay = SimpleNamespace(request=relay)
    payload = json.dumps({"action": "pair", "code": "AB12CD34"})
    assert request(server, "POST", "/api/cloud-relay", payload, {})[0] == 403
    assert calls == []
    status, headers, body = request(server, "POST", "/api/cloud-relay", payload, session(server))
    assert status == 200 and body == b"private-token"
    assert headers["Cache-Control"] == "no-store"
    assert calls == ["pair"]
    assert not list(server.app.root.rglob("*.json"))


def test_relay_unexpected_errors_are_redacted(server):
    def broken(_):
        raise RuntimeError("secret-token-and-code")

    server.app.cloud_relay = SimpleNamespace(request=broken)
    status, _, body = request(
        server, "POST", "/api/cloud-relay", b'{"action":"session"}', session(server)
    )
    assert status == 502
    assert b"secret-token" not in body


def test_cloud_modules_are_served_with_javascript_type(server):
    for name in ("cloud-ui", "cloud-client", "cloud-vault"):
        status, headers, _ = request(server, "GET", "/" + name + ".mjs")
        assert status == 200
        assert "javascript" in headers["Content-Type"]


def test_normal_app_does_not_enable_cli_cloud_routes(server):
    headers = session(server)
    for action in ("pair", "revoke", "list", "import"):
        assert request(server, "POST", "/api/cloud-" + action, b"{}", headers)[0] == 410
    status, _, body = request(server, "GET", "/api/cloud-status", headers=headers)
    assert status == 200
    assert json.loads(body)["state"] == "browser-managed"


def test_relay_concurrency_gate_rejects_before_transport(server):
    server.app.relay_slots = threading.BoundedSemaphore(1)
    server.app.cloud_relay = SimpleNamespace(request=lambda _: (b"ok", "text/plain"))
    server.app.relay_slots.acquire()
    try:
        status, _, _ = request(server, "POST", "/api/cloud-relay", b"{}", session(server))
        assert status == 503
    finally:
        server.app.relay_slots.release()


def test_static_page_preview_endpoint_is_authenticated_and_serves_png(server):
    import json
    import runpy
    import time

    raw = runpy.run_path("scripts/release-smoke.py")["synthetic_archive"]()
    doc = server.app.library.add(raw, provenance={"provider": "test"})
    payload = json.dumps(
        dict(
            document=doc["id"],
            page=doc["pages"][0]["id"],
            settings=dict(
                width=1404,
                height=1872,
                offset_x=702,
                offset_y=0,
                output_width=234,
                seconds=6,
                fps=6,
                backend="python",
            ),
        )
    ).encode()
    assert request(server, "POST", "/api/page-preview", payload, {})[0] == 403
    headers = session(server)
    code, _, body = request(server, "POST", "/api/page-preview", payload, headers)
    assert code == 200
    result = json.loads(body)
    for _ in range(100):
        code, _, body = request(
            server, "GET", "/api/page-preview?id=" + result["id"], headers=headers
        )
        result = json.loads(body)
        if result["state"] not in ("queued", "running"):
            break
        time.sleep(0.05)
    assert result["state"] == "complete", result
    assert request(server, "GET", result["url"])[0] == 403
    code, _, png = request(server, "GET", result["url"], headers=headers)
    assert code == 200 and png.startswith(b"\x89PNG")
