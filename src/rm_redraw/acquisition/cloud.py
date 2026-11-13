"""Read synced notebooks through a locally paired rmctl companion."""

import json
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from zlib import error as ZlibError

from .archive import MAX_BYTES, archive_hashes
from .source import UUID_RE

_JSON_LIMIT = 16 * 1024 * 1024
_READ_TIMEOUT = 60
_EXPORT_TIMEOUT = 180
_SUPPORTED_KINDS = ("notebook", "annotated-pdf")
_INSTALL_MESSAGE = "To browse cloud notebooks, install rmctl 1.2.0 and add it to PATH."
_LIST_ERROR = "rmctl returned an unexpected document list. Use rmctl 1.2.0."


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
    """Allowlist the rmctl reads needed for browsing and importing one document."""

    def __init__(self, executable: Path | None = None) -> None:
        self._executable = executable.absolute() if executable is not None else _find_executable()
        self._lock = threading.Lock()

    def status(self) -> dict[str, str]:
        """Report local executable availability without contacting reMarkable."""
        if not self._available():
            return {"state": "missing", "message": _INSTALL_MESSAGE}
        return {
            "state": "available",
            "message": "rmctl is available. Browse the cloud to check your paired profile.",
        }

    def list_documents(self) -> list[CloudDocument]:
        with self._lock, tempfile.TemporaryDirectory(prefix="rm-redraw-cloud-") as directory:
            records = self._read_json(Path(directory), ["find"], timeout=_READ_TIMEOUT)
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

    def _available(self) -> bool:
        path = self._executable
        return (
            path is not None
            and (os.name != "nt" or path.suffix.lower() == ".exe")
            and path.is_file()
            and os.access(path, os.X_OK)
        )

    def _read_json(self, workspace: Path, args: list[str], *, timeout: int) -> object:
        if not self._available():
            raise CloudError(_INSTALL_MESSAGE)
        # A profile may be locally configured, but only the production cloud hosts are used.
        env = {name: value for name, value in os.environ.items() if not name.startswith("RMCLOUD_")}
        env.update({key: str(workspace) for key in ("TEMP", "TMP", "TMPDIR")})
        argv = [str(self._executable), "--offline=false", "--no-cache", "--json", *args]
        with tempfile.TemporaryFile(dir=workspace) as stdout:
            try:
                result = subprocess.run(
                    argv,
                    stdin=subprocess.DEVNULL,
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
            if result.returncode == 3:
                raise CloudNotPairedError(
                    "Use the local terminal to pair your rmctl profile first."
                )
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


def _find_executable() -> Path | None:
    """Search absolute PATH entries without Windows' implicit current directory."""
    filename = "rmctl.exe" if os.name == "nt" else "rmctl"
    for item in os.environ.get("PATH", "").split(os.pathsep):
        directory = Path(item)
        if directory.is_absolute() and (path := shutil.which(str(directory / filename))):
            return Path(path)
    return None
