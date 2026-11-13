from __future__ import annotations

import json
from pathlib import Path

import pytest

from rm_redraw.acquisition import Document, SshDeviceSource

ROOT_DRAWINGS_ID = "11111111-1111-4111-8111-111111111111"
NOTE_ID = "22222222-2222-4222-8222-222222222222"
PAGE_ID = "33333333-3333-4333-8333-333333333333"
DUPLICATE_FOLDER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
DUPLICATE_NOTE_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


class FakeSsh:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.files = {
            f"/store/{ROOT_DRAWINGS_ID}.metadata": json.dumps(
                {"visibleName": "Drawings", "parent": "", "type": "CollectionType"}
            ).encode(),
            f"/store/{NOTE_ID}.metadata": json.dumps(
                {"visibleName": "Small note", "parent": ROOT_DRAWINGS_ID, "type": "DocumentType"}
            ).encode(),
            f"/store/{NOTE_ID}.content": json.dumps(
                {
                    "cPages": {
                        "pages": [
                            {
                                "id": PAGE_ID,
                                "idx": {"timestamp": "2:1", "value": "ba"},
                            }
                        ]
                    }
                }
            ).encode(),
            f"/store/{NOTE_ID}.pagedata": b"Blank\n",
            f"/store/{NOTE_ID}/{PAGE_ID}.rm": b"reMarkable .lines file, version=6          ",
            f"/store/{DUPLICATE_FOLDER_ID}.metadata": json.dumps(
                {
                    "visibleName": "Drawings",
                    "parent": NOTE_ID,
                    "type": "CollectionType",
                }
            ).encode(),
            f"/store/{DUPLICATE_NOTE_ID}.metadata": json.dumps(
                {"visibleName": "Drawings", "parent": "", "type": "DocumentType"}
            ).encode(),
        }
        self.stats = {path: (len(contents), 1234) for path, contents in self.files.items()}

    def __call__(self, remote_command: str) -> bytes:
        self.commands.append(remote_command)
        if remote_command == "cat /etc/os-release":
            return b'IMG_VERSION="3.27.3.0"\nVERSION="5.7.126 (scarthgap)"\n'
        if remote_command == "cat /sys/devices/soc0/machine 2>/dev/null; true":
            return b"reMarkable Chiappa\n"
        if remote_command == "find /store -maxdepth 1 -type f -name '*.metadata' -print":
            return "\n".join(
                path for path in self.files if path.endswith(".metadata") and path.count("/") == 2
            ).encode()
        if remote_command.startswith("cat "):
            return self.files[remote_command.removeprefix("cat ")]
        if remote_command.startswith("stat -c '%s %Y' "):
            path = remote_command.removeprefix("stat -c '%s %Y' ")
            size, mtime = self.stats[path]
            return f"{size} {mtime}\n".encode()
        if remote_command.startswith("test -f "):
            path = remote_command.removeprefix("test -f ").removesuffix(" && printf yes; true")
            return b"yes" if path in self.files else b""
        raise AssertionError(f"unexpected command: {remote_command}")


def test_lists_documents_and_reconstructs_page_ids() -> None:
    source = SshDeviceSource(store="/store", run=FakeSsh())

    documents = source.list_documents()

    assert documents == [
        Document(
            id=ROOT_DRAWINGS_ID,
            visible_name="Drawings",
            parent_id=None,
            document_type="CollectionType",
            page_ids=(),
        ),
        Document(
            id=DUPLICATE_FOLDER_ID,
            visible_name="Drawings",
            parent_id=NOTE_ID,
            document_type="CollectionType",
            page_ids=(),
        ),
        Document(
            id=DUPLICATE_NOTE_ID,
            visible_name="Drawings",
            parent_id=None,
            document_type="DocumentType",
            page_ids=(),
        ),
        Document(
            id=NOTE_ID,
            visible_name="Small note",
            parent_id=ROOT_DRAWINGS_ID,
            document_type="DocumentType",
            page_ids=(PAGE_ID,),
        ),
    ]
    assert source.find_folder("Drawings").id == ROOT_DRAWINGS_ID
    assert source.get_document(NOTE_ID).page_ids == (PAGE_ID,)


def test_snapshot_copies_only_stable_files_and_writes_hash_manifest(tmp_path: Path) -> None:
    fake = FakeSsh()
    source = SshDeviceSource(store="/store", run=fake)

    snapshot = source.snapshot_document(NOTE_ID, tmp_path)

    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    copied_paths = {entry["path"] for entry in manifest["files"]}
    assert copied_paths == {
        f"raw/{NOTE_ID}.metadata",
        f"raw/{NOTE_ID}.content",
        f"raw/{NOTE_ID}.pagedata",
        f"raw/pages/{PAGE_ID}.rm",
    }
    assert manifest["schema_version"] == 1
    assert manifest["source"]["firmware"] == "3.27.3.0"
    assert manifest["source"]["build"] == "5.7.126 (scarthgap)"
    assert manifest["source"]["machine"] == "reMarkable Chiappa"
    assert manifest["document"]["page_ids"] == [PAGE_ID]
    assert all(entry["sha256"] for entry in manifest["files"])
    assert all(entry["stability"] == "size-mtime-stable" for entry in manifest["files"])
    assert (snapshot / "raw" / "pages" / f"{PAGE_ID}.rm").read_bytes() == fake.files[
        f"/store/{NOTE_ID}/{PAGE_ID}.rm"
    ]
    with pytest.raises(FileExistsError):
        source.snapshot_document(NOTE_ID, tmp_path)


def test_get_document_reads_only_the_requested_record() -> None:
    fake = FakeSsh()
    source = SshDeviceSource(store="/store", run=fake)

    document = source.get_document(NOTE_ID)

    assert document.id == NOTE_ID
    assert not any(command.startswith("find ") for command in fake.commands)
