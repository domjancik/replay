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
        content = json.loads(archive.read(content_name))
        metadata_name = content_name.removesuffix(".content") + ".metadata"
        metadata = json.loads(archive.read(metadata_name)) if metadata_name in hashes else {}
        entries = content.get("pages")
        if not entries:
            entries = content.get("cPages", {}).get("pages", [])
            entries = [e for e in entries if not e.get("deleted", {}).get("value", False)]
            if entries and all(isinstance(e.get("idx", {}).get("value"), str) for e in entries):
                entries = sorted(entries, key=lambda e: e["idx"]["value"])
        if not entries:
            raise ValueError("Notebook has no recorded page order")
        ids = [e if isinstance(e, str) else e["id"] for e in entries]
        if any(not isinstance(p, str) or not p or len(p) > 128 for p in ids):
            raise ValueError("Invalid page identifier")
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


class Library:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[dict]:
        return [
            json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(self.root.glob("*/notebook.json"))
        ]

    def get(self, document_id: str) -> dict:
        # Opaque local IDs only; no HTTP request can supply a filesystem path.
        if len(document_id) != 32 or any(c not in "0123456789abcdef" for c in document_id):
            raise ValueError("Invalid local notebook ID")
        path = self.root / document_id / "notebook.json"
        if not path.is_file():
            raise ValueError("Unknown local notebook")
        return json.loads(path.read_text(encoding="utf-8"))

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
        (folder / "notebook.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record


def validate_pdf(data: bytes, pages: int) -> None:
    from pypdf import PdfReader

    if len(data) > MAX_BYTES or not data.startswith(b"%PDF"):
        raise ValueError("Invalid or oversized paired PDF")
    if len(PdfReader(BytesIO(data)).pages) != pages:
        raise ValueError("Paired PDF page count does not match the notebook")
