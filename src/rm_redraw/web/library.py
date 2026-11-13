"""Bounded archive inspection and immutable local notebook copies."""

import hashlib
import json
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
from uuid import uuid4
from zipfile import ZipFile

from rm_redraw.acquisition.archive import MAX_BYTES, archive_hashes


def inspect_archive(data: bytes) -> dict:
    hashes = archive_hashes(data)
    with ZipFile(BytesIO(data)) as archive:
        content_names = [n for n in hashes if n.endswith(".content")]
        if len(content_names) != 1:
            raise ValueError("Expected one notebook .content record")
        content_name = content_names[0]
        metadata_name = content_name.removesuffix(".content") + ".metadata"
        content = _notebook_object(archive.read(content_name))
        metadata = _notebook_object(archive.read(metadata_name)) if metadata_name in hashes else {}
        entries = content.get("pages")
        if entries is not None and not isinstance(entries, list):
            raise ValueError("Invalid notebook metadata: pages must be a list")
        if not entries:
            entries = _current_pages(content)
        if not entries:
            raise ValueError("Notebook has no recorded page order")
        if any(not isinstance(entry, (str, dict)) for entry in entries):
            raise ValueError("Invalid notebook metadata: page entries must contain identifiers")
        ids = [e if isinstance(e, str) else e.get("id") for e in entries]
        if any(not isinstance(p, str) or not p or len(p) > 128 for p in ids):
            raise ValueError("Invalid notebook metadata: invalid page identifier")
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate ordered page identifiers")
        members = {}
        for name in hashes:
            if name.endswith(".rm"):
                page_id = PurePosixPath(name).stem
                if page_id in members:
                    raise ValueError("Duplicate .rm page identifier")
                members[page_id] = name
        return {
            "name": str(metadata.get("visibleName") or "Imported notebook")[:240],
            "pages": [
                {"id": p, "number": i + 1, "available": p in members, "member": members.get(p)}
                for i, p in enumerate(ids)
            ],
            "sha256": hashlib.sha256(data).hexdigest(),
            "member_hashes": hashes,
        }


def _notebook_object(data: bytes) -> dict:
    try:
        record = json.loads(data)
    except (ValueError, RecursionError) as error:
        raise ValueError("Invalid notebook metadata: expected a JSON object") from error
    if not isinstance(record, dict):
        raise ValueError("Invalid notebook metadata: expected a JSON object")
    return record


def _current_pages(content: dict) -> list[dict]:
    current = content.get("cPages", {})
    if not isinstance(current, dict):
        raise ValueError("Invalid notebook metadata: cPages must be an object")
    entries = current.get("pages", [])
    if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
        raise ValueError("Invalid notebook metadata: cPages.pages must contain page objects")
    if any(
        not isinstance(entry.get(key, {}), dict) for entry in entries for key in ("idx", "deleted")
    ):
        raise ValueError("Invalid notebook metadata: invalid page ordering or deletion marker")
    entries = [e for e in entries if not e.get("deleted", {}).get("value", False)]
    if all(isinstance(e.get("idx", {}).get("value"), str) for e in entries):
        entries.sort(key=lambda e: e["idx"]["value"])
    return entries


class Library:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[dict]:
        records = []
        for path in sorted(self.root.glob("*/notebook.json")):
            try:
                records.append(self.get(path.parent.name))
            except ValueError:
                continue
        return records

    def get(self, document_id: str) -> dict:
        # Opaque local IDs only; no HTTP request can supply a filesystem path.
        if not _local_id(document_id):
            raise ValueError("Invalid local notebook ID")
        path = self.root / document_id / "notebook.json"
        if not path.is_file():
            raise ValueError("Unknown local notebook")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(record, dict)
                or record.get("id") != document_id
                or not isinstance(record.get("pages"), list)
                or not isinstance(record.get("name"), str)
                or type(record.get("has_pdf")) is not bool
            ):
                raise ValueError("Malformed local notebook record")
        except (OSError, ValueError, RecursionError) as error:
            raise ValueError("Unreadable local notebook record") from error
        return record

    def source(self, document_id: str) -> Path:
        self.get(document_id)
        return self.root / document_id / "document.rmdoc"

    def add(self, data: bytes, *, provenance: dict, pdf: bytes | None = None) -> dict:
        record = inspect_archive(data)
        record.update(
            id=uuid4().hex,
            acquired_at=datetime.now(UTC).isoformat(),
            provenance=provenance,
            has_pdf=pdf is not None,
        )
        if pdf is not None:
            validate_pdf(pdf, len(record["pages"]))
            record["pdf_sha256"] = hashlib.sha256(pdf).hexdigest()
        folder = self.root / record["id"]
        folder.mkdir()
        (folder / "document.rmdoc").write_bytes(data)
        if pdf is not None:
            (folder / "native.pdf").write_bytes(pdf)
        pending = folder / "notebook.tmp"
        pending.write_text(json.dumps(record, indent=2), encoding="utf-8")
        pending.replace(folder / "notebook.json")
        return record


def _local_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 32
        and all(c in "0123456789abcdef" for c in value)
    )


def validate_pdf(data: bytes, pages: int) -> None:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    if len(data) > MAX_BYTES or not data.startswith(b"%PDF"):
        raise ValueError("Invalid or oversized paired PDF")
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("Paired PDF is password-protected")
        page_count = len(reader.pages)
    except (PyPdfError, RecursionError) as error:
        raise ValueError("Unreadable paired PDF") from error
    if page_count != pages:
        raise ValueError("Paired PDF page count does not match the notebook")
