import pytest

from rm_redraw.acquisition.usb import UsbReader


def test_usb_only_allows_uuid_routes():
    reader = UsbReader()
    with pytest.raises(ValueError):
        reader.documents("../other")
    with pytest.raises(ValueError):
        reader.capture("http://elsewhere", include_pdf=False)


def test_capture_rejects_changed_source(monkeypatch):
    from test_library import notebook

    reader = UsbReader()
    a = notebook([], pages=["a", "b"])
    b = notebook([], pages=["b", "a"])
    answers = iter([a, b])
    monkeypatch.setattr(reader, "_get", lambda route: next(answers))
    with pytest.raises(ValueError, match="changed"):
        reader.capture("00000000-0000-0000-0000-000000000001", include_pdf=False)


def test_failed_pdf_capture_preserves_raw_attempt(tmp_path, monkeypatch):
    from test_library import notebook

    reader = UsbReader()
    raw = notebook([], pages=["a", "b"])

    def fetch(route):
        if route.endswith("/placeholder"):
            raise TimeoutError("export timed out")
        return raw

    monkeypatch.setattr(reader, "_get", fetch)
    with pytest.raises(TimeoutError):
        reader.capture(
            "00000000-0000-0000-0000-000000000001",
            include_pdf=True,
            attempt_directory=tmp_path / "attempt",
        )
    assert (tmp_path / "attempt/read-1.rmdoc").read_bytes() == raw
    assert "export timed out" in (tmp_path / "attempt/status.json").read_text()
