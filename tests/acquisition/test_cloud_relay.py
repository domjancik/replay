import base64
import hashlib
import io
import json
import socket
from email.message import Message
from urllib.error import HTTPError, URLError

import pytest

from rm_redraw.acquisition import cloud_relay
from rm_redraw.acquisition.cloud_relay import CloudRelay, CloudRelayError

AUTH = "https://webapp-prod.cloud.remarkable.engineering"
SYNC = "https://internal.cloud.remarkable.com"
DEVICE_ID = "21368b92-a648-4dd2-a488-c89172f383e7"
DEVICE_TOKEN = "test-device-token"


def user_token(region):
    claims = base64.urlsafe_b64encode(json.dumps({"tectonic": region}).encode())
    return "test." + claims.decode().rstrip("=") + ".signature"


class Reply(io.BytesIO):
    def __init__(self, data, *, status=200, headers=None):
        super().__init__(data)
        self.status = status
        self.headers = Message()
        for name, value in (headers or {}).items():
            self.headers[name] = value


@pytest.fixture
def wire(monkeypatch):
    calls = []
    replies = []

    class Opener:
        addheaders = []

        def open(self, request, timeout):
            calls.append(request)
            assert 0 < timeout <= 15
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

    monkeypatch.setattr(cloud_relay, "build_opener", lambda *args: Opener())
    return calls, replies


def test_pair_session_and_revoke_use_fixed_auth_endpoints(wire):
    calls, replies = wire
    replies.extend(
        [Reply(b" test-device-token\n"), Reply(b"test-user-token"), Reply(b"", status=204)]
    )
    relay = CloudRelay()
    assert relay.request({"action": "pair", "code": "CODE1234", "device_id": DEVICE_ID}) == (
        b"test-device-token",
        "text/plain; charset=utf-8",
    )
    assert relay.request({"action": "session", "token": DEVICE_TOKEN}) == (
        b"test-user-token",
        "text/plain; charset=utf-8",
    )
    assert relay.request({"action": "revoke", "token": DEVICE_TOKEN}) == (b"{}", "application/json")
    pair, session, revoke = calls
    assert [call.get_method() for call in calls] == ["POST"] * 3
    assert pair.full_url == f"{AUTH}/token/json/2/device/new"
    assert pair.get_header("Authorization") is None
    assert pair.get_header("Content-type") == "application/json"
    assert json.loads(pair.data) == {
        "code": "code1234",
        "deviceDesc": "desktop-macos",
        "deviceID": DEVICE_ID,
    }
    assert session.full_url == f"{AUTH}/token/json/2/user/new"
    assert revoke.full_url == f"{AUTH}/token/json/3/device/delete"
    for call in (session, revoke):
        assert call.data is None
        assert call.get_header("Content-type") is None
        assert call.get_header("Authorization") == f"Bearer {DEVICE_TOKEN}"


def test_root_falls_back_only_after_v4_404_and_files_use_index_names(wire):
    calls, replies = wire
    raw = b"synthetic notebook page"
    digest = hashlib.sha256(raw).hexdigest()
    root = json.dumps({"hash": digest, "generation": 17, "schemaVersion": 4}).encode()
    replies.extend([Reply(b"", status=404), Reply(root), Reply(raw)])
    relay = CloudRelay()
    token = user_token("Europe")
    assert relay.request({"action": "root", "token": token}) == (root, "application/json")
    filename = f"{DEVICE_ID}/{DEVICE_ID}.rm"
    assert relay.request(
        {"action": "file", "token": token, "hash": digest, "filename": filename}
    ) == (raw, "application/octet-stream")
    prefix = "https://europe.tectonic.remarkable.com"
    assert [call.full_url for call in calls] == [
        f"{prefix}/sync/v4/root",
        f"{prefix}/sync/v3/root",
        f"{prefix}/sync/v3/files/{digest}",
    ]
    assert [call.get_header("Rm-filename") for call in calls] == ["roothash", "roothash", filename]
    assert all(call.get_header("Authorization") == f"Bearer {token}" for call in calls)


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "put", "token": DEVICE_TOKEN},
        {"action": "root", "token": "a\r\nInjected: x"},
        {"action": "root", "token": DEVICE_TOKEN, "host": "https://example.invalid"},
        {"action": "file", "token": DEVICE_TOKEN, "hash": "../x", "filename": "root.docSchema"},
        {"action": "file", "token": DEVICE_TOKEN, "hash": "0" * 64, "filename": "../escape"},
        {"action": "file", "token": DEVICE_TOKEN, "hash": "0" * 64, "filename": "file\nname"},
        {"action": "pair", "code": "code1234", "device_id": "not-a-uuid"},
        {"action": ["pair"]},
    ],
)
def test_rejects_invalid_payloads_before_network(wire, payload):
    calls, _ = wire
    with pytest.raises(CloudRelayError) as failure:
        CloudRelay().request(payload)
    assert failure.value.status == 400
    assert calls == []


def test_provider_failure_is_safe_and_does_not_retry_authorization(wire):
    calls, replies = wire
    replies.append(Reply(b"private response", status=403))
    relay = CloudRelay()
    with pytest.raises(CloudRelayError) as failure:
        relay.request({"action": "root", "token": user_token("bad.example")})
    assert failure.value.status == 403
    assert "private" not in str(failure.value)
    assert len(calls) == 1
    assert calls[0].full_url == f"{SYNC}/sync/v4/root"
    replies.append(Reply(b"", status=401))
    assert relay.request({"action": "revoke", "token": DEVICE_TOKEN}) == (b"{}", "application/json")


def test_unreachable_region_falls_back_to_fixed_sync_host(wire):
    calls, replies = wire
    body = json.dumps({"hash": "a" * 64, "generation": 17}).encode()
    replies.extend([URLError(socket.gaierror("private DNS diagnostic")), Reply(body)])
    assert CloudRelay().request({"action": "root", "token": user_token("Europe")}) == (
        body,
        "application/json",
    )
    assert [call.full_url for call in calls] == [
        "https://europe.tectonic.remarkable.com/sync/v4/root",
        f"{SYNC}/sync/v4/root",
    ]


def test_rejects_redirect_and_bad_blob_digest(wire):
    calls, replies = wire
    replies.extend(
        [
            HTTPError(f"{SYNC}/sync/v4/root", 302, "private", Message(), io.BytesIO()),
            Reply(b"wrong bytes"),
        ]
    )
    relay = CloudRelay()
    with pytest.raises(CloudRelayError) as redirect:
        relay.request({"action": "root", "token": DEVICE_TOKEN})
    assert redirect.value.status == 502
    with pytest.raises(CloudRelayError, match="hash") as checksum:
        relay.request(
            {
                "action": "file",
                "token": DEVICE_TOKEN,
                "hash": "0" * 64,
                "filename": f"{DEVICE_ID}.metadata",
            }
        )
    assert checksum.value.status == 502
    assert len(calls) == 2


def test_bounds_reply_without_content_length(wire, monkeypatch):
    _, replies = wire
    monkeypatch.setattr(cloud_relay, "_TOKEN_LIMIT", 4)
    replies.extend([Reply(b"x" * 5), Reply(b"x", headers={"Content-Length": "500"})])
    for _ in range(2):
        with pytest.raises(CloudRelayError, match="limit") as failure:
            CloudRelay().request({"action": "session", "token": "auth"})
        assert failure.value.status == 502
