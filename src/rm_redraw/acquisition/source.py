"""SSH-backed read-only document discovery and snapshotting."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

DEFAULT_STORE = "/home/root/.local/share/remarkable/xochitl"
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@dataclass(frozen=True)
class Document:
    """A document or collection reconstructed from native metadata."""

    id: str
    visible_name: str
    parent_id: str | None
    document_type: str
    page_ids: tuple[str, ...]


class DeviceSource(ABC):
    """Read-only source for native reMarkable documents."""

    @abstractmethod
    def list_documents(self) -> list[Document]:
        """Return all known documents and collections."""

    @abstractmethod
    def find_folder(self, name: str) -> Document:
        """Return the uniquely named collection."""

    @abstractmethod
    def get_document(self, document_id: str) -> Document:
        """Return one document by UUID."""

    @abstractmethod
    def snapshot_document(self, document_id: str, destination_root: Path) -> Path:
        """Create an immutable local snapshot and return its directory."""


RemoteRunner = Callable[[str], bytes]


class SshDeviceSource(DeviceSource):
    """Read native xochitl records through ordinary passwordless SSH configuration."""

    def __init__(
        self,
        host: str = "10.11.99.1",
        store: str = DEFAULT_STORE,
        run: RemoteRunner | None = None,
    ) -> None:
        self.host = host
        self.store = store.rstrip("/")
        self._run = run or self._run_ssh
        self._documents: dict[str, Document] | None = None

    def list_documents(self) -> list[Document]:
        self._load_documents()
        assert self._documents is not None
        return sorted(
            self._documents.values(), key=lambda document: (document.visible_name, document.id)
        )

    def find_folder(self, name: str) -> Document:
        folders = [
            document
            for document in self.list_documents()
            if document.visible_name == name and document.document_type == "CollectionType"
        ]
        root_folders = [document for document in folders if document.parent_id is None]
        if len(root_folders) == 1:
            return root_folders[0]
        if len(folders) != 1:
            raise LookupError(f"expected one collection named {name!r}, found {len(folders)}")
        return folders[0]

    def get_document(self, document_id: str) -> Document:
        self._require_uuid(document_id)
        if self._documents is not None:
            try:
                return self._documents[document_id]
            except KeyError as error:
                raise LookupError(f"unknown document UUID {document_id}") from error
        metadata_path = f"{self.store}/{document_id}.metadata"
        if not self._exists(metadata_path):
            raise LookupError(f"unknown document UUID {document_id}")
        return self._document_from_metadata(document_id, self._read_json(metadata_path))

    def snapshot_document(self, document_id: str, destination_root: Path) -> Path:
        document = self.get_document(document_id)
        snapshot = destination_root / document.id
        if snapshot.exists():
            raise FileExistsError(f"snapshot already exists: {snapshot}")
        snapshot.mkdir(parents=True)
        files: list[dict[str, object]] = []
        try:
            for suffix in (".metadata", ".content", ".pagedata"):
                source = f"{self.store}/{document.id}{suffix}"
                if self._exists(source):
                    self._copy_stable(
                        source, PurePosixPath("raw") / f"{document.id}{suffix}", snapshot, files
                    )
            for page_id in document.page_ids:
                page_root = f"{self.store}/{document.id}/{page_id}"
                self._copy_stable(
                    page_root + ".rm", PurePosixPath("raw/pages") / f"{page_id}.rm", snapshot, files
                )
                metadata_path = page_root + ".metadata"
                if self._exists(metadata_path):
                    self._copy_stable(
                        metadata_path,
                        PurePosixPath("raw/pages") / f"{page_id}.metadata",
                        snapshot,
                        files,
                    )
            device_info = self._device_info()
            manifest = {
                "schema_version": 1,
                "source": {
                    "provider": "ssh",
                    "device_address": self.host,
                    **device_info,
                    "acquired_at_utc": datetime.now(UTC).isoformat(),
                },
                "document": {
                    "id": document.id,
                    "visible_name": document.visible_name,
                    "parent_id": document.parent_id,
                    "type": document.document_type,
                    "page_ids": list(document.page_ids),
                },
                "files": files,
            }
            (snapshot / "manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        except Exception:
            # Retain a partial directory for diagnosis, but never present it as a snapshot.
            raise
        return snapshot

    def _device_info(self) -> dict[str, str]:
        release: dict[str, str] = {}
        for line in self._run("cat /etc/os-release").decode("utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator:
                release[key] = value.strip().strip('"')
        machine = self._run("cat /sys/devices/soc0/machine 2>/dev/null; true").decode().strip()
        return {
            "firmware": release.get("IMG_VERSION", "unknown"),
            "build": release.get("VERSION", "unknown"),
            "machine": machine or "unknown",
        }

    def _load_documents(self) -> None:
        if self._documents is not None:
            return
        metadata_paths = self._run(
            f"find {self.store} -maxdepth 1 -type f -name '*.metadata' -print"
        )
        records: dict[str, Document] = {}
        for raw_path in metadata_paths.decode("utf-8").splitlines():
            path = raw_path.strip()
            document_id = Path(path).stem
            if not UUID_RE.fullmatch(document_id):
                continue
            records[document_id] = self._document_from_metadata(document_id, self._read_json(path))
        self._documents = records

    def _document_from_metadata(self, document_id: str, metadata: dict[str, object]) -> Document:
        content_path = f"{self.store}/{document_id}.content"
        content = self._read_json(content_path) if self._exists(content_path) else {}
        pages = content.get("pages")
        if not isinstance(pages, list):
            compact_pages = content.get("cPages")
            pages = compact_pages.get("pages", []) if isinstance(compact_pages, dict) else []
        if not isinstance(pages, list):
            pages = []
        page_ids = tuple(
            page_id
            for page in pages
            if isinstance(page_id := page if isinstance(page, str) else page.get("id"), str)
            and UUID_RE.fullmatch(page_id)
        )
        parent = metadata.get("parent")
        return Document(
            id=document_id,
            visible_name=str(metadata.get("visibleName", "")),
            parent_id=parent if isinstance(parent, str) and UUID_RE.fullmatch(parent) else None,
            document_type=str(metadata.get("type", "")),
            page_ids=page_ids,
        )

    def _copy_stable(
        self,
        source: str,
        relative_path: PurePosixPath,
        snapshot: Path,
        files: list[dict[str, object]],
    ) -> None:
        self._require_safe_relative_path(relative_path)
        before = self._stat(source)
        payload = self._run(f"cat {source}")
        after = self._stat(source)
        if before != after or len(payload) != before[0]:
            raise RuntimeError(f"source file changed while being copied: {source}")
        target = snapshot.joinpath(*relative_path.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        files.append(
            {
                "path": relative_path.as_posix(),
                "byte_size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "source_mtime": after[1],
                "stability": "size-mtime-stable",
            }
        )

    def _exists(self, source: str) -> bool:
        # Keep SSH successful when an optional xochitl sidecar is absent.
        return self._run(f"test -f {source} && printf yes; true") == b"yes"

    def _stat(self, source: str) -> tuple[int, int]:
        output = self._run(f"stat -c '%s %Y' {source}").decode("ascii").strip().split()
        if len(output) != 2:
            raise RuntimeError(f"unexpected stat output for {source!r}")
        return int(output[0]), int(output[1])

    def _read_json(self, source: str) -> dict[str, object]:
        value = json.loads(self._run(f"cat {source}").decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"expected JSON object in {source}")
        return value

    @staticmethod
    def _require_uuid(value: str) -> None:
        if not UUID_RE.fullmatch(value):
            raise ValueError(f"invalid UUID: {value!r}")

    @staticmethod
    def _require_safe_relative_path(path: PurePosixPath) -> None:
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"unsafe snapshot path: {path}")

    def _run_ssh(self, remote_command: str) -> bytes:
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", self.host, remote_command],
            check=True,
            capture_output=True,
        )
        return result.stdout
