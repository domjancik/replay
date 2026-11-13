import json
import os
import subprocess
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from rm_redraw.acquisition.cloud import CloudDocument, CloudError, CloudNotPairedError, CloudSource

NOTEBOOK_ID = "5a190e3f-7cf0-4df6-a26e-3a9db703ac0c"
OTHER_ID = "ea7dd8e7-2704-4786-a059-7112ad6e6971"


def record(document_id=NOTEBOOK_ID, **changes):
    return {
        "id": document_id,
        "name": "Ink & paper",
        "path": "/Projects/Ink & paper",
        "kind": "notebook",
        "size": 124,
        "trashed": False,
        **changes,
    }


def notebook_bytes(document_id=NOTEBOOK_ID, *, unsafe=False):
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr(f"{document_id}.metadata", b'{"visibleName":"Ink & paper"}')
        archive.writestr(f"{document_id}.content", b'{"pages":["page1"]}')
        archive.writestr(f"{document_id}/page1.rm", b"synthetic test bytes")
        if unsafe:
            archive.writestr("../escape", b"reject")
    return stream.getvalue()


@pytest.fixture
def executable(tmp_path):
    path = tmp_path / "rmctl.exe"
    path.touch(mode=0o700)
    return path


def write_json(stream, value):
    stream.write(json.dumps(value).encode())


def test_lists_visible_nested_documents_without_using_cloud_overrides(executable, monkeypatch):
    monkeypatch.setenv("RMCLOUD_AUTH_HOST", "https://example.invalid")
    monkeypatch.setenv("RMCLOUD_WIRE_LOG", "bodies")
    monkeypatch.setenv("RMCTL_PROFILE", "drawings")

    def run(argv, *, stdout, stdin, stderr, shell, timeout, env, cwd, check):
        assert argv == [str(executable), "--offline=false", "--no-cache", "--json", "find"]
        assert shell is False and check is False
        assert stdin == stderr == subprocess.DEVNULL
        assert 0 < timeout <= 60
        assert env["RMCTL_PROFILE"] == "drawings"
        assert "RMCLOUD_AUTH_HOST" not in env and "RMCLOUD_WIRE_LOG" not in env
        assert env["TMPDIR"] == env["TEMP"] == env["TMP"] == str(cwd)
        write_json(
            stdout,
            [
                record(),
                record(OTHER_ID, kind="annotated-pdf", name="Annotated"),
                record(kind="folder"),
                record(kind="pdf"),
                record(trashed=True),
            ],
        )
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", run)
    assert CloudSource(executable).list_documents() == [
        CloudDocument(NOTEBOOK_ID, "Ink & paper", "/Projects/Ink & paper", "notebook"),
        CloudDocument(OTHER_ID, "Annotated", "/Projects/Ink & paper", "annotated-pdf"),
    ]


def test_pairing_code_only_goes_to_stdin_and_revocation_uses_fixed_args(executable, monkeypatch):
    code = "testA123"
    calls = []

    def run(argv, *, stdout, stdin=None, input=None, stderr, shell, timeout, **kwargs):
        calls.append(argv[1:])
        assert all(code not in str(arg) for arg in argv)
        assert shell is False and stderr == subprocess.DEVNULL
        assert 0 < timeout <= 60
        if argv[1:] == ["register", "--help"]:
            assert stdin == subprocess.DEVNULL and input is None
            stdout.write(b"Flags:\n      --code-stdin   read the code from standard input\n")
        elif argv[4:] == ["register", "--code-stdin"]:
            assert input == code.encode("ascii") + b"\n"
            assert stdin is None
            assert stdout == subprocess.DEVNULL
        else:
            assert argv[4:] == ["logout", "--revoke"]
            assert stdin == subprocess.DEVNULL and input is None
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", run)
    source = CloudSource(executable)
    assert source.status()["can_pair"] is True
    assert source.status()["pairing"] == "unknown"
    source.pair(code)
    assert source.status()["pairing"] == "paired"
    source.revoke()
    assert source.status()["pairing"] == "unpaired"
    assert calls == [
        ["register", "--help"],
        ["--offline=false", "--no-cache", "--json", "register", "--code-stdin"],
        ["--offline=false", "--no-cache", "--json", "logout", "--revoke"],
    ]


def test_stock_companion_never_receives_the_code(executable, monkeypatch):
    def run(argv, *, stdout, **kwargs):
        assert argv[1:] == ["register", "--help"]
        assert kwargs.get("input") is None
        stdout.write(b"Usage: register <code>\n")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", run)
    source = CloudSource(executable)
    assert source.status()["can_pair"] is False
    with pytest.raises(CloudError, match="patched rmctl"):
        source.pair("testA123")


def test_separate_pairing_companion_uses_same_profile_and_keeps_stock_reads(
    executable, tmp_path, monkeypatch
):
    pairing_executable = tmp_path / "rmctl-pairing.exe"
    pairing_executable.touch(mode=0o700)
    monkeypatch.setenv("RMCTL_PROFILE", "rm-redraw")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RMCTL_CONFIG_DIR", "profile")
    monkeypatch.setenv("RMCTL_CONFIG_FILE", "settings/config.toml")
    monkeypatch.setenv("RMCTL_CACHE_DIR", "cache")
    monkeypatch.setenv("XDG_CONFIG_HOME", "xdg-config")
    monkeypatch.setenv("XDG_CACHE_HOME", "xdg-cache")
    calls = []

    def run(argv, *, stdout, env, **kwargs):
        calls.append((argv[0], argv[1:]))
        assert env["RMCTL_PROFILE"] == "rm-redraw"
        assert env["RMCTL_CONFIG_DIR"] == str(tmp_path / "profile")
        assert env["RMCTL_CONFIG_FILE"] == str(tmp_path / "settings/config.toml")
        assert env["RMCTL_CACHE_DIR"] == str(tmp_path / "cache")
        assert env["XDG_CONFIG_HOME"] == str(tmp_path / "xdg-config")
        assert env["XDG_CACHE_HOME"] == str(tmp_path / "xdg-cache")
        if argv[1:] == ["register", "--help"]:
            stdout.write(b"      --code-stdin    read from standard input\n")
        elif argv[-1] == "find":
            write_json(stdout, [])
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", run)
    source = CloudSource(executable, pairing_executable=pairing_executable)
    monkeypatch.chdir(tmp_path.parent)
    source.pair("testA123")
    assert source.list_documents() == []
    source.revoke()
    assert calls == [
        (str(pairing_executable), ["register", "--help"]),
        (
            str(pairing_executable),
            ["--offline=false", "--no-cache", "--json", "register", "--code-stdin"],
        ),
        (str(executable), ["--offline=false", "--no-cache", "--json", "find"]),
        (
            str(executable),
            ["--offline=false", "--no-cache", "--json", "logout", "--revoke"],
        ),
    ]


@pytest.mark.parametrize("code", [None, "0123", "012345678", "abcdefgh\n", "non-ASCIIé"])
def test_invalid_pairing_code_does_not_launch_companion(executable, monkeypatch, code):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid pairing code reached the companion")

    monkeypatch.setattr(subprocess, "run", forbidden)
    with pytest.raises(CloudError, match="eight"):
        CloudSource(executable).pair(code)


def test_pairing_failure_does_not_echo_upstream_or_mark_paired(executable, monkeypatch):
    def run(argv, *, stdout, **kwargs):
        if argv[1:] == ["register", "--help"]:
            stdout.write(b"      --code-stdin    read from standard input\n")
            return subprocess.CompletedProcess(argv, 0)
        assert stdout == subprocess.DEVNULL
        return subprocess.CompletedProcess(argv, 1, stderr=b"testA123")

    monkeypatch.setattr(subprocess, "run", run)
    source = CloudSource(executable)
    with pytest.raises(CloudError, match="pairing failed") as failure:
        source.pair("testA123")
    assert "testA123" not in str(failure.value)
    assert "private-output" not in str(failure.value)
    assert source.status()["pairing"] == "unknown"


@pytest.mark.parametrize(
    ("code", "error_type", "message"),
    [
        (3, CloudNotPairedError, "Pair"),
        (2, CloudError, "1.2.0"),
        (1, CloudError, "local terminal"),
    ],
)
def test_reports_safe_cli_failures(executable, monkeypatch, code, error_type, message):
    def run(argv, *, stdout, **kwargs):
        stdout.write(b"private-token")
        return subprocess.CompletedProcess(argv, code, stderr=b"private-path")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(error_type, match=message) as failure:
        CloudSource(executable).list_documents()
    assert "private" not in str(failure.value)


def test_reports_timeout_without_echoing_command(executable, monkeypatch):
    def run(argv, *, timeout, **kwargs):
        raise subprocess.TimeoutExpired(argv, timeout, output=b"private-token")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(CloudError, match="timed out") as failure:
        CloudSource(executable).list_documents()
    assert "private" not in str(failure.value)
    assert str(executable) not in str(failure.value)


@pytest.mark.parametrize("payload", [b"private-token", b"{}", b"[null]", b"[[[]]]"])
def test_rejects_unexpected_listing_without_echoing_output(executable, monkeypatch, payload):
    def run(argv, *, stdout, **kwargs):
        stdout.write(payload)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(CloudError, match="invalid JSON|unexpected document list") as failure:
        CloudSource(executable).list_documents()
    assert "private" not in str(failure.value)


def test_missing_binary_and_invalid_ids_do_not_launch_process(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    source = CloudSource()
    assert source.status()["state"] == "missing"
    with pytest.raises(CloudError, match="install rmctl"):
        source.list_documents()
    for value in ("-o", "notes", "https://example.invalid", NOTEBOOK_ID + "\n", None):
        with pytest.raises(ValueError, match="UUID"):
            source.download_archive(value)
    assert CloudSource(tmp_path / "missing.exe").status()["state"] == "missing"


def test_discovery_ignores_working_directory(tmp_path, monkeypatch):
    executable_name = "rmctl.exe" if os.name == "nt" else "rmctl"
    candidate = tmp_path / executable_name
    candidate.touch(mode=0o700)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NoDefaultCurrentDirectoryInExePath", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "missing"))
    assert CloudSource().status()["state"] == "missing"


@pytest.mark.parametrize(
    ("details", "expected"),
    [
        (record(kind="folder"), "visible notebook"),
        (record(trashed=True), "visible notebook"),
        (record(OTHER_ID), "visible notebook"),
        (record(size=128 * 1024 * 1024 + 1), "128 MiB"),
    ],
)
def test_preflights_export_before_requesting_an_archive(executable, monkeypatch, details, expected):
    def run(argv, *, stdout, **kwargs):
        assert argv[4:] == ["stat", NOTEBOOK_ID]
        write_json(stdout, details)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(CloudError, match=expected):
        CloudSource(executable).download_archive(NOTEBOOK_ID)


@pytest.mark.parametrize(
    ("payload", "documents", "expected"),
    [
        (notebook_bytes(), 1, None),
        (notebook_bytes(), 2, "one cloud document"),
        (notebook_bytes(OTHER_ID), 1, "selected document"),
        (notebook_bytes(unsafe=True), 1, "invalid .rmdoc"),
        (b"not a zip archive", 1, "invalid .rmdoc"),
    ],
)
def test_export_reads_only_validated_archive_and_cleans_temp(
    executable, monkeypatch, payload, documents, expected
):
    outputs = []

    def run(argv, *, stdout, timeout, cwd, **kwargs):
        if argv[4:] == ["stat", NOTEBOOK_ID]:
            write_json(stdout, record())
        else:
            assert argv[4:7] == ["export", NOTEBOOK_ID, "-o"]
            output = Path(argv[7])
            assert output == cwd / "selected.rmdoc"
            assert 0 < timeout <= 180
            assert not output.exists()
            output.write_bytes(payload)
            outputs.append(output)
            write_json(stdout, {"path": str(output), "documents": documents, "files": 3})
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", run)
    if expected:
        with pytest.raises(CloudError, match=expected):
            CloudSource(executable).download_archive(NOTEBOOK_ID)
    else:
        assert CloudSource(executable).download_archive(NOTEBOOK_ID) == payload
    assert len(outputs) == 1
    assert not outputs[0].parent.exists()
