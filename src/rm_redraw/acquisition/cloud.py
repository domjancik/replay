"""Read synced notebooks through a locally paired rmctl companion."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from zlib import error as ZlibError

from .archive import MAX_BYTES, archive_hashes
from .source import UUID_RE

_JSON_LIMIT = 16 * 1024 * 1024
_CAPABILITY_LIMIT = 32 * 1024
_CAPABILITY_TIMEOUT = 5
_READ_TIMEOUT = 60
_EXPORT_TIMEOUT = 180
_SUPPORTED_KINDS = ("notebook", "annotated-pdf")
_INSTALL_MESSAGE = "To browse cloud notebooks, install rmctl 1.2.0 and add it to PATH."
_LIST_ERROR = "rmctl returned an unexpected document list. Use rmctl 1.2.0."
_PAIRING_CODE = re.compile(r"[A-Za-z0-9]{8}")
_PAIRING_CAPABILITY = re.compile(rb"(?m)^\s+--code-stdin\s{2,}")
_FLAGS = ("--offline=false", "--no-cache", "--json")
_PROFILE_PATHS = (
    "RMCTL_CONFIG_DIR",
    "RMCTL_CONFIG_FILE",
    "RMCTL_CACHE_DIR",
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
)


class CloudError(RuntimeError):
    """A cloud companion failure safe to display in the local UI."""


class CloudNotPairedError(CloudError):
    """The selected rmctl profile does not have a device registration."""


@dataclass(frozen=True)
class CloudDocument:
    id: str
    name: str
    path: str
    kind: str


class CloudSource:
    """Allowlist account operations and reads for a local rmctl profile."""

    def __init__(
        self, executable: Path | None = None, *, pairing_executable: Path | None = None
    ) -> None:
        self._launch_directory = Path.cwd()
        self._executable = (
            executable.absolute() if executable is not None else _find_executable("rmctl")
        )
        self._pairing_executable = (
            pairing_executable.absolute()
            if pairing_executable is not None
            else _find_executable("rmctl-pairing")
            if executable is None
            else None
        )
        self._lock = threading.Lock()
        self._pairing = "unknown"
        self._can_pair: bool | None = None

    def status(self) -> dict[str, str | bool]:
        """Report local executable availability without contacting reMarkable."""
        if not _available(self._executable):
            return {
                "state": "missing",
                "message": _INSTALL_MESSAGE,
                "can_pair": False,
                "pairing": "unknown",
            }
        # The capability probe asks for local help only. Avoid waiting for an active export.
        if self._can_pair is None and self._lock.acquire(blocking=False):
            try:
                self._supports_pairing()
            finally:
                self._lock.release()
        return {
            "state": "available",
            "message": "rmctl is available. Browse the cloud to check your paired profile.",
            "can_pair": self._can_pair is True,
            "pairing": self._pairing,
        }

    def pair(self, code: str) -> None:
        """Register using the patched companion's stdin-only pairing mode."""
        if not isinstance(code, str) or not _PAIRING_CODE.fullmatch(code):
            raise CloudError("Enter the eight letters or digits from your reMarkable pairing code.")
        with self._lock, tempfile.TemporaryDirectory(prefix="rm-redraw-cloud-") as directory:
            if not self._supports_pairing():
                raise CloudError("Install the patched rmctl companion to pair inside the app.")
            self._change_pairing(
                Path(directory),
                ["register", "--code-stdin"],
                code=code.encode("ascii") + b"\n",
                companion=self._pairing_executable,
                failure="Cloud pairing failed. Check your local profile or generate a fresh code.",
            )
            self._pairing = "paired"

    def revoke(self) -> None:
        """Revoke the active local profile registration and forget its credential."""
        with self._lock, tempfile.TemporaryDirectory(prefix="rm-redraw-cloud-") as directory:
            self._change_pairing(
                Path(directory),
                ["logout", "--revoke"],
                failure="Cloud revocation failed. Check your local profile and connection.",
            )
            self._pairing = "unpaired"

    def list_documents(self) -> list[CloudDocument]:
        with self._lock, tempfile.TemporaryDirectory(prefix="rm-redraw-cloud-") as directory:
            records = self._read_json(Path(directory), ["find"], timeout=_READ_TIMEOUT)
            self._pairing = "paired"
        if not isinstance(records, list):
            raise CloudError(_LIST_ERROR)
        documents = []
        for record in records:
            if not isinstance(record, dict):
                raise CloudError(_LIST_ERROR)
            if record.get("kind") not in _SUPPORTED_KINDS or record.get("trashed") is not False:
                continue
            document_id, name, path, kind = (
                record.get(key) for key in ("id", "name", "path", "kind")
            )
            if not all(isinstance(value, str) for value in (document_id, name, path, kind)):
                raise CloudError(_LIST_ERROR)
            if not UUID_RE.fullmatch(document_id):
                raise CloudError(_LIST_ERROR)
            documents.append(CloudDocument(document_id, name, path, kind))
        return documents

    def download_archive(self, document_id: str) -> bytes:
        if not isinstance(document_id, str) or not UUID_RE.fullmatch(document_id):
            raise ValueError("Invalid cloud document UUID")
        with self._lock, tempfile.TemporaryDirectory(prefix="rm-redraw-cloud-") as directory:
            workspace = Path(directory)
            self._check_document(workspace, document_id)
            output = workspace / "selected.rmdoc"
            report = self._read_json(
                workspace, ["export", document_id, "-o", str(output)], timeout=_EXPORT_TIMEOUT
            )
            if (
                not isinstance(report, dict)
                or type(report.get("documents")) is not int
                or report["documents"] != 1
            ):
                raise CloudError("rmctl did not export exactly one cloud document.")
            try:
                with output.open("rb") as stream:
                    data = stream.read(MAX_BYTES + 1)
            except OSError:
                raise CloudError("rmctl did not produce a readable .rmdoc export.") from None

        if len(data) > MAX_BYTES:
            raise CloudError("Cloud notebook exceeds the 128 MiB import limit.")
        try:
            names = archive_hashes(data)
        except (ValueError, RuntimeError, NotImplementedError, EOFError, ZlibError):
            raise CloudError("rmctl returned an invalid .rmdoc export.") from None
        content_records = [name for name in names if name.endswith(".content")]
        if content_records != [f"{document_id}.content"] or f"{document_id}.metadata" not in names:
            raise CloudError("The exported archive does not match the selected document.")
        return data

    def _check_document(self, workspace: Path, document_id: str) -> None:
        record = self._read_json(workspace, ["stat", document_id], timeout=_READ_TIMEOUT)
        if (
            not isinstance(record, dict)
            or record.get("id") != document_id
            or record.get("kind") not in _SUPPORTED_KINDS
            or record.get("trashed") is not False
        ):
            raise CloudError("Select a visible notebook or annotated PDF from the cloud list.")
        size = record.get("size")
        if type(size) is not int or size < 0:
            raise CloudError("rmctl could not determine the size of the selected document.")
        if size > MAX_BYTES:
            raise CloudError("Cloud notebook exceeds the 128 MiB import limit.")

    def _supports_pairing(self) -> bool:
        if not _available(self._executable):
            return False
        if self._can_pair is None:
            with tempfile.TemporaryDirectory(prefix="rm-redraw-cloud-") as directory:
                workspace = Path(directory)
                with tempfile.TemporaryFile(dir=workspace) as stdout:
                    try:
                        result = self._run(
                            workspace,
                            ["register", "--help"],
                            stdout,
                            _CAPABILITY_TIMEOUT,
                            companion=self._pairing_executable,
                        )
                    except CloudError:
                        return False
                    stdout.seek(0)
                    self._can_pair = result.returncode == 0 and bool(
                        _PAIRING_CAPABILITY.search(stdout.read(_CAPABILITY_LIMIT))
                    )
        return self._can_pair

    def _change_pairing(
        self,
        workspace: Path,
        args: list[str],
        *,
        code: bytes | None = None,
        companion: Path | None = None,
        failure: str,
    ) -> None:
        result = self._run(
            workspace,
            [*_FLAGS, *args],
            subprocess.DEVNULL,
            _READ_TIMEOUT,
            code=code,
            companion=companion,
        )
        if result.returncode:
            raise CloudError(failure)

    def _run(
        self,
        workspace: Path,
        args: list[str],
        stdout: BinaryIO | int,
        timeout: int,
        *,
        code: bytes | None = None,
        companion: Path | None = None,
    ) -> subprocess.CompletedProcess:
        executable = self._executable if companion is None else companion
        if not _available(executable):
            raise CloudError(_INSTALL_MESSAGE)
        # A profile may be locally configured, but only the production cloud hosts are used.
        env = {name: value for name, value in os.environ.items() if not name.startswith("RMCLOUD_")}
        # rmctl runs from a fresh staging directory. Anchor profile overrides to app launch.
        for name in _PROFILE_PATHS:
            if path := env.get(name):
                env[name] = str(self._launch_directory / path)
        env.update({key: str(workspace) for key in ("TEMP", "TMP", "TMPDIR")})
        argv = [str(executable), *args]
        input_stream = {"stdin": subprocess.DEVNULL} if code is None else {"input": code}
        try:
            return subprocess.run(
                argv,
                **input_stream,
                stdout=stdout,
                stderr=subprocess.DEVNULL,
                cwd=workspace,
                env=env,
                shell=False,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise CloudError(
                "The cloud request timed out. Retry when the connection is stable."
            ) from None
        except OSError:
            raise CloudError("Could not start rmctl. Check the local installation.") from None

    def _read_json(self, workspace: Path, args: list[str], *, timeout: int) -> object:
        with tempfile.TemporaryFile(dir=workspace) as stdout:
            result = self._run(workspace, [*_FLAGS, *args], stdout, timeout)
            if result.returncode == 3:
                self._pairing = "unpaired"
                raise CloudNotPairedError("Pair your rmctl profile first.")
            if result.returncode == 2:
                raise CloudError("rmctl did not recognize the command. Use rmctl 1.2.0.")
            if result.returncode:
                raise CloudError(
                    "Cloud request failed. Check your connection and rmctl in a local terminal."
                )
            stdout.seek(0)
            data = stdout.read(_JSON_LIMIT + 1)
        if len(data) > _JSON_LIMIT:
            raise CloudError("rmctl returned more than 16 MiB of document metadata.")
        try:
            return json.loads(data.decode("utf-8"))
        except (ValueError, RecursionError):
            raise CloudError("rmctl returned invalid JSON. Use rmctl 1.2.0.") from None


def _available(path: Path | None) -> bool:
    return (
        path is not None
        and (os.name != "nt" or path.suffix.lower() == ".exe")
        and path.is_file()
        and os.access(path, os.X_OK)
    )


def _find_executable(name: str) -> Path | None:
    """Search absolute PATH entries without Windows' implicit current directory."""
    filename = f"{name}.exe" if os.name == "nt" else name
    for item in os.environ.get("PATH", "").split(os.pathsep):
        directory = Path(item)
        if directory.is_absolute() and (path := shutil.which(str(directory / filename))):
            return Path(path)
    return None
