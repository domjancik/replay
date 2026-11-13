import json
from io import BytesIO
from zipfile import ZipFile

import pytest

from rm_redraw.web.library import Library, inspect_archive, validate_pdf


def notebook(entries, members=("a", "b"), **content):
    data = BytesIO()
    with ZipFile(data, "w") as z:
        z.writestr("doc.metadata", json.dumps({"visibleName": "A <notebook>"}))
        z.writestr("doc.content", json.dumps({"cPages": {"pages": entries}, **content}))
        for page in members:
            z.writestr(f"doc/{page}.rm", b"not parsed for catalog")
    return data.getvalue()


def test_catalog_preserves_page_order_and_blank_slots():
    result = inspect_archive(
        notebook(
            [
                {"id": "a", "idx": {"value": "c"}},
                {"id": "blank", "idx": {"value": "b"}},
                {"id": "b", "idx": {"value": "a"}},
                {"id": "gone", "idx": {"value": "d"}, "deleted": {"value": True}},
            ]
        )
    )
    assert result["name"] == "A <notebook>"
    assert [p["id"] for p in result["pages"]] == ["b", "blank", "a"]
    assert result["pages"][1]["available"] is False
    assert [p["number"] for p in result["pages"]] == [1, 2, 3]


def test_legacy_page_order():
    result = inspect_archive(notebook([], pages=["b", "a"]))
    assert [p["id"] for p in result["pages"]] == ["b", "a"]


def test_rejects_unsafe_archive_members():
    with pytest.raises(ValueError, match="unsafe"):
        inspect_archive(notebook([], members=("../../escape",)))


def test_missing_order_not_invented():
    with pytest.raises(ValueError, match="page order"):
        inspect_archive(notebook([]))


@pytest.mark.parametrize(
    "content",
    [b"null", b"{", b'{"cPages": []}', b'{"pages": [{"idx": "x"}]}'],
)
def test_reports_invalid_notebook_metadata(content):
    data = BytesIO()
    with ZipFile(data, "w") as archive:
        archive.writestr("doc.content", content)
    with pytest.raises(ValueError, match="Invalid notebook metadata"):
        inspect_archive(data.getvalue())


def test_reports_malformed_pdf():
    with pytest.raises(ValueError, match="Unreadable paired PDF"):
        validate_pdf(b"%PDF-1.7\n", 1)


def test_library_ignores_incomplete_catalog_record(tmp_path):
    library = Library(tmp_path)
    valid = library.add(notebook([], pages=["a"]), provenance={"provider": "test"})
    bad = tmp_path / ("c" * 32)
    bad.mkdir()
    record = bad / "notebook.json"
    record.write_text("{", encoding="utf-8")
    assert [entry["id"] for entry in library.list()] == [valid["id"]]
    with pytest.raises(ValueError, match="Unreadable local notebook record"):
        library.get(bad.name)
    assert record.read_text(encoding="utf-8") == "{"
