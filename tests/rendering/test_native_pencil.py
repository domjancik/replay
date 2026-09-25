import numpy as np
import pytest

from rm_redraw.rendering.native_pencil import draw_batch


def test_invalid_buffers_reject_before_loading_library():
    with pytest.raises(ValueError, match="uint8"):
        draw_batch(np.zeros((4, 4)), [], 1, 1, 255)
    with pytest.raises(ValueError, match="contiguous"):
        draw_batch(np.zeros((4, 4), dtype=np.uint8)[:, ::2], [], 1, 1, 255)
    with pytest.raises(ValueError, match="finite"):
        draw_batch(np.zeros((4, 4), dtype=np.uint8), [(1, 2, np.nan, 0.5)], 1, 1, 255)


def test_missing_explicit_library_fails_actionably(monkeypatch, tmp_path):
    monkeypatch.setenv("RM_REDRAW_PENCIL_LIBRARY", str(tmp_path / "missing.dll"))
    with pytest.raises(RuntimeError, match="Rust pencil library"):
        draw_batch(np.zeros((4, 4), dtype=np.uint8), [(1, 2, 1, 0.5)], 1, 1, 255)


def test_native_batch_matches_python_when_built(monkeypatch):
    from rm_redraw.rendering.native_pencil import library_path
    from rm_redraw.rendering.pencil import dab

    monkeypatch.delenv("RM_REDRAW_PENCIL_LIBRARY", raising=False)
    if not library_path().exists():
        pytest.skip("optional Rust pencil kernel is not built")
    for sx, sy in [(4, 4), (1.3333333333333333, 0.875), (2.125, 3.75)]:
        samples = [
            (2 + i * 0.83, 12 + i * 0.13, 1 + (i % 13) * 0.7, (i % 31) / 30) for i in range(90)
        ]
        python = np.zeros((151, 173), np.uint8)
        rust = python.copy()
        for x, y, radius, pressure in samples:
            dab(python, x, y, radius, pressure, sx, sy, 173, origin_x=17, origin_y=19)
        draw_batch(rust, samples, sx, sy, 173, origin_x=17, origin_y=19)
        np.testing.assert_array_equal(rust, python)


def test_native_progressive_texture_matches_python_when_built(monkeypatch):
    from PIL import Image

    from rm_redraw.rendering.native_pencil import library_path
    from rm_redraw.rendering.texture import draw_texture
    from rm_redraw.rendering.types import NormalizedPoint, NormalizedStroke

    monkeypatch.delenv("RM_REDRAW_PENCIL_LIBRARY", raising=False)
    if not library_path().exists():
        pytest.skip("optional Rust pencil kernel is not built")
    stroke = NormalizedStroke(
        "native",
        "layer",
        (40, 70, 190, 173),
        7,
        (
            NormalizedPoint(-3.17, 12.39, 64, 16, 10, 24),
            NormalizedPoint(51.67, 38.98, 192, 80, 135, 96),
            NormalizedPoint(85.13, 18.43, 250, 3, 230, None),
        ),
        14,
    )
    for progress in [0, 9.7, 45.3, 999]:
        python = Image.new("RGBA", (180, 140), (210, 170, 130, 201))
        rust = python.copy()
        draw_texture(python, stroke, progress, 1.3, 0.7)
        draw_texture(rust, stroke, progress, 1.3, 0.7, pencil_backend="rust")
        assert rust.tobytes() == python.tobytes()


def test_native_status_is_not_silently_ignored(monkeypatch):
    from types import SimpleNamespace

    from rm_redraw.rendering import native_pencil

    monkeypatch.setattr(
        native_pencil, "_library", lambda path: SimpleNamespace(rm_pencil_draw=lambda *args: 3)
    )
    with pytest.raises(RuntimeError, match="status 3"):
        draw_batch(np.zeros((4, 4), dtype=np.uint8), [(1, 2, 1, 0.5)], 1, 1, 255)


def test_native_rejects_malformed_empty_samples():
    with pytest.raises(ValueError, match="shape"):
        draw_batch(np.zeros((4, 4), dtype=np.uint8), np.empty((0, 3)), 1, 1, 255)


def test_wrong_library_abi_rejected(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from rm_redraw.rendering import native_pencil

    def version():
        return 99

    monkeypatch.setattr(
        native_pencil.ctypes, "CDLL", lambda path: SimpleNamespace(rm_pencil_kernel_version=version)
    )
    with pytest.raises(RuntimeError, match="ABI version"):
        native_pencil._library(str(tmp_path / "wrong-abi.dll"))
