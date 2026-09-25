"""Fixed-host, serialized, read-only USB HTTP operations."""

import hashlib
import json
import threading
from pathlib import Path
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

from .archive import MAX_BYTES, archive_hashes
from .source import UUID_RE


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("USB redirects are not permitted")


class UsbReader:
    def __init__(self):
        self.lock = threading.Lock()
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def _get(self, route: str) -> bytes:
        with self.opener.open("http://10.11.99.1" + route, timeout=60) as response:
            data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("USB response exceeds 128 MiB")
        return data

    def documents(self, folder: str = "") -> list[dict]:
        if folder and not UUID_RE.fullmatch(folder):
            raise ValueError("Invalid folder UUID")
        with self.lock:
            records = json.loads(self._get("/documents/" + folder))
        if not isinstance(records, list):
            raise ValueError("Unexpected USB document listing")
        result = []
        for record in records:
            if not isinstance(record, dict) or not UUID_RE.fullmatch(str(record.get("ID", ""))):
                continue
            result.append(
                {
                    "id": record["ID"],
                    "name": str(record.get("VisibleName", record.get("VissibleName", ""))),
                    "folder": record.get("Type") == "CollectionType",
                    "file_type": record.get("fileType", ""),
                }
            )
        return result

    def capture(
        self, document_id: str, *, include_pdf: bool, attempt_directory: Path | None = None
    ) -> tuple[bytes, bytes | None, dict]:
        if not UUID_RE.fullmatch(document_id):
            raise ValueError("Invalid document UUID")
        if attempt_directory is not None:
            attempt_directory.mkdir(parents=True, exist_ok=False)

        def retain(name, data):
            if attempt_directory is not None:
                (attempt_directory / name).write_bytes(data)

        try:
            with self.lock:
                first = self._get(f"/download/{document_id}/rmdoc")
                retain("read-1.rmdoc", first)
                first_hashes = archive_hashes(first)
                pdf = self._get(f"/download/{document_id}/placeholder") if include_pdf else None
                if pdf is not None:
                    retain("native.pdf", pdf)
                second = self._get(f"/download/{document_id}/rmdoc")
                retain("read-2.rmdoc", second)
                if first_hashes != archive_hashes(second):
                    raise ValueError(
                        "Notebook changed during import; close it on the tablet and retry"
                    )
            retain(
                "status.json", json.dumps({"state": "stable", "document_id": document_id}).encode()
            )
        except Exception as error:
            retain(
                "status.json",
                json.dumps(
                    {"state": "failed", "document_id": document_id, "error": str(error)}
                ).encode(),
            )
            raise
        return (
            first,
            pdf,
            {
                "provider": "usb-api",
                "host": "10.11.99.1",
                "document_id": document_id,
                "raw_member_stability": "two reads have identical member hashes",
                "read_sha256": [hashlib.sha256(x).hexdigest() for x in (first, second)],
                "pdf_pairing": "export between stable raw reads" if pdf else None,
            },
        )
