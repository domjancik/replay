import http.client
import json
import threading

import pytest

from rm_redraw.web.server import create_server


@pytest.fixture
def server(tmp_path):
    server = create_server(tmp_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    server.app.jobs.close()
    thread.join()


def request(server, method, path, data=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
    conn.request(method, path, body=data, headers=headers or {})
    response = conn.getresponse()
    result = response.status, dict(response.getheaders()), response.read()
    conn.close()
    return result


def session(server):
    status, headers, _ = request(server, "GET", "/")
    assert status == 200
    cookie = headers["Set-Cookie"].split(";")[0]
    status, _, body = request(server, "GET", "/api/session", headers={"Cookie": cookie})
    assert status == 200
    return {
        "Cookie": cookie,
        "X-Replay-Token": json.loads(body)["token"],
        "Origin": f"http://127.0.0.1:{server.server_port}",
        "Content-Type": "application/json",
    }


def test_local_service_rejects_foreign_host_and_unauthenticated_api(server):
    assert request(server, "GET", "/", headers={"Host": "evil.example"})[0] == 403
    assert request(server, "GET", "/api/library")[0] == 403


def test_cross_origin_mutations_rejected(server):
    headers = session(server)
    headers["Origin"] = "https://evil.example"
    assert request(server, "POST", "/api/jobs", b"{}", headers)[0] == 403
    headers["Origin"] = f"http://127.0.0.1:{server.server_port}"
    headers.pop("X-Replay-Token")
    assert request(server, "POST", "/api/jobs", b"{}", headers)[0] == 403


def test_upload_size_rejection_identifies_limit(server):
    headers = session(server)
    headers.update(
        {"Content-Type": "application/octet-stream", "Content-Length": str(128 * 1024**2 + 1)}
    )
    status, _, body = request(server, "POST", "/api/upload", b"", headers)
    assert status == 413
    assert "128 MiB" in json.loads(body)["error"]


def test_wrong_upload_media_type_returns_415(server):
    status, _, body = request(server, "POST", "/api/upload", b"{}", session(server))
    assert status == 415
    assert "application/octet-stream" in json.loads(body)["error"]


def test_invalid_job_settings_return_actionable_error(server):
    data = json.dumps({"document": "invalid", "page": "page", "settings": []})
    status, _, body = request(server, "POST", "/api/jobs", data, session(server))
    assert status == 400
    assert json.loads(body)["error"] == "Settings must be a JSON object"


def test_simultaneous_upload_is_rejected_before_reading_body(server):
    from test_library import notebook

    headers = session(server)
    headers["Content-Type"] = "application/octet-stream"
    raw = notebook([], pages=["a"])
    server.app.import_lock.acquire()
    try:
        status, _, body = request(server, "POST", "/api/upload", raw, headers)
    finally:
        server.app.import_lock.release()
    assert status == 409
    assert "import is already in progress" in json.loads(body)["error"]
    assert server.app.library.list() == []


def test_upload_and_media_paths_are_scoped(server):
    from test_library import notebook

    headers = session(server)
    headers["Content-Type"] = "application/octet-stream"
    status, _, body = request(
        server, "POST", "/api/upload", notebook([], pages=["a", "b"]), headers
    )
    assert status == 200
    assert json.loads(body)["pages"][0]["id"] == "a"
    assert request(server, "GET", "/media/../../pyproject.toml", headers=headers)[0] == 404
    assert request(server, "GET", "/api/library", headers=headers)[0] == 200


def test_video_range_serving_and_output_allowlist(server):
    headers = session(server)
    job_id = "a" * 32
    folder = server.app.jobs.root / job_id / "output"
    folder.mkdir(parents=True)
    (folder / "replay.mp4").write_bytes(b"0123456789")
    server.app.jobs.jobs[job_id] = {"id": job_id, "state": "complete", "created": 1}
    headers["Range"] = "bytes=2-5"
    status, response_headers, body = request(
        server, "GET", f"/media/{job_id}/replay.mp4", headers=headers
    )
    assert status == 206
    assert body == b"2345"
    assert response_headers["Content-Range"] == "bytes 2-5/10"
    assert request(server, "GET", f"/media/{job_id}/render.log", headers=headers)[0] == 400
    headers["Range"] = "bytes=999-"
    assert request(server, "GET", f"/media/{job_id}/replay.mp4", headers=headers)[0] == 416


def test_cloud_requires_session_and_import_token(server):
    from types import SimpleNamespace

    server.app.cloud = SimpleNamespace(
        status=lambda: {"state": "missing", "message": "Install rmctl"}
    )
    assert request(server, "GET", "/api/cloud-status")[0] == 403
    status, _, body = request(server, "GET", "/api/cloud-status", headers=session(server))
    assert status == 200
    assert json.loads(body)["state"] == "missing"
    assert request(server, "POST", "/api/cloud-list", b"{}", {})[0] == 403


def test_cloud_import_reuses_validated_local_library(server):
    from types import SimpleNamespace

    from test_library import notebook

    raw = notebook([], pages=["a"])
    calls = []
    identifier = "11111111-1111-4111-8111-111111111111"

    def download(document_id):
        calls.append(document_id)
        return raw

    server.app.cloud = SimpleNamespace(download_archive=download)
    status, _, body = request(
        server, "POST", "/api/cloud-import", json.dumps({"id": identifier}), session(server)
    )
    assert status == 200, body
    result = json.loads(body)
    assert calls == [identifier]
    assert result["provenance"]["provider"] == "rmctl-cloud"
    assert server.app.library.source(result["id"]).read_bytes() == raw


def test_cloud_import_obeys_shared_import_lock(server):
    from types import SimpleNamespace

    def forbidden(_):
        raise AssertionError("Cloud helper must not run while another import is active")

    server.app.cloud = SimpleNamespace(download_archive=forbidden)
    headers = session(server)
    server.app.import_lock.acquire()
    try:
        status, _, _ = request(server, "POST", "/api/cloud-import", b'{"id":"any"}', headers)
    finally:
        server.app.import_lock.release()
    assert status == 409
