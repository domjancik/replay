import numpy as np
from PIL import Image

from rm_redraw.rendering import texture
from rm_redraw.rendering.types import NormalizedPoint, NormalizedStroke


def test_small_stroke_allocates_local_alpha(monkeypatch):
    allocated = []
    original = np.zeros

    def zeros(shape, *args, **kwargs):
        allocated.append(shape)
        return original(shape, *args, **kwargs)

    monkeypatch.setattr(texture.np, "zeros", zeros)
    stroke = NormalizedStroke(
        "small",
        "layer",
        (0, 0, 0, 255),
        2,
        (NormalizedPoint(100, 100, 128, 16, 0, 24), NormalizedPoint(110, 105, 128, 16, 0, 24)),
        12,
    )
    texture.draw_texture(Image.new("RGBA", (1404, 1872), "white"), stroke, 20, 1, 1)
    assert allocated
    assert max(h * w for h, w in allocated) < 100 * 100


def test_local_dab_matches_global_coordinates():
    for current, brush, boundary in [
        (False, False, False),
        (False, True, False),
        (True, True, False),
        (True, False, True),
    ]:
        full = np.zeros((180, 240), dtype=np.uint8)
        local = np.zeros((100, 120), dtype=np.uint8)
        args = (35.13, 29.79, 6.4, 0.34, 0.78, brush, False, 19, 2.3, 1.7, 173, current, boundary)
        texture._dab(full, *args)
        texture._dab(local, *args, origin_x=30, origin_y=10)
        np.testing.assert_array_equal(local, full[10:110, 30:150])
        assert full.sum() == local.sum()


def test_offpage_stroke_does_not_allocate_alpha(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("offpage stroke allocated an alpha buffer")

    monkeypatch.setattr(texture.np, "zeros", unexpected)
    stroke = NormalizedStroke(
        "offpage",
        "layer",
        (0, 0, 0, 255),
        2,
        (NormalizedPoint(-100, -100, 128, 16, 0, 24), NormalizedPoint(-90, -95, 128, 16, 0, 24)),
        12,
    )
    image = Image.new("RGBA", (200, 200), "white")
    before = image.tobytes()
    texture.draw_texture(image, stroke, 20, 1, 1)
    assert image.tobytes() == before
