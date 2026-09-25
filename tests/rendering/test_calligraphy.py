from dataclasses import replace

import numpy as np
import pytest
from PIL import Image

from rm_redraw.rendering.geometry import prefix_points
from rm_redraw.rendering.types import NormalizedPoint, NormalizedStroke


def _stroke(points=None, **changes):
    stroke = NormalizedStroke(
        "calligraphy",
        "ink",
        (20, 80, 160, 128),
        2,
        points or (NormalizedPoint(20, 40, width=24), NormalizedPoint(100, 40, width=24)),
        tool_code=21,
    )
    return replace(stroke, **changes)


def _render(stroke, progress=1, scale_x=1, scale_y=1):
    from rm_redraw.rendering.calligraphy import draw_calligraphy

    image = Image.new("RGBA", (round(140 * scale_x), round(120 * scale_y)))
    draw_calligraphy(image, prefix_points(stroke, progress), stroke, scale_x, scale_y)
    return image


@pytest.mark.parametrize("raw_width", [4, 24, 96])
@pytest.mark.parametrize("scale", [1, 0.5])
def test_calligraphy_quarter_width_at_pixel_centers(raw_width, scale):
    points = (NormalizedPoint(20, 40, width=raw_width), NormalizedPoint(100, 40, width=raw_width))
    image = _render(_stroke(points, rgba=(0, 0, 0, 255)), scale_x=scale, scale_y=scale)
    alpha = np.asarray(image)[:, round(60 * scale), 3] / 255
    assert alpha.sum() == pytest.approx(raw_width / 4 * scale, abs=0.12)


def test_retained_pressure_direction_speed_and_thickness_do_not_rescale_width():
    initial = _stroke()
    changed = replace(
        initial,
        thickness_scale=8,
        points=tuple(replace(p, pressure=250, direction=128, speed=240) for p in initial.points),
    )
    assert _render(initial).tobytes() == _render(changed).tobytes()


def test_single_and_coincident_points_are_blank_but_short_path_has_ink():
    p = NormalizedPoint(50, 50, width=48)
    assert _render(_stroke((p,))).getbbox() is None
    assert _render(_stroke((p, p))).getbbox() is None
    assert _render(_stroke((p, replace(p, x=50.01)))).getbbox() is not None


def test_diagonal_is_antialiased_and_source_rgba_applied_once():
    stroke = _stroke((NormalizedPoint(20, 20, width=24), NormalizedPoint(100, 80, width=24)))
    image = _render(stroke)
    pixels = np.asarray(image)
    assert np.any((pixels[:, :, 3] > 0) & (pixels[:, :, 3] < 128))
    assert pixels[:, :, 3].max() == 128
    np.testing.assert_array_equal(
        pixels[pixels[:, :, 3] == 128][:, :3],
        np.tile([20, 80, 160], (int((pixels[:, :, 3] == 128).sum()), 1)),
    )
    repeated = replace(stroke, points=(*stroke.points, *reversed(stroke.points)))
    assert _render(repeated).tobytes() == image.tobytes()


def test_progressive_original_segment_geometry_keeps_completed_prefix_identical():
    stroke = _stroke(
        (
            NormalizedPoint(10, 20, width=24),
            NormalizedPoint(80, 60, width=24),
            NormalizedPoint(115, 25, width=24),
        )
    )
    first = _render(stroke, 0.55)
    second = _render(stroke, 0.8)
    assert first.crop((0, 0, 30, 120)).tobytes() == second.crop((0, 0, 30, 120)).tobytes()
    assert _render(stroke, 1).tobytes() == _render(stroke).tobytes()


def test_anisotropic_viewport_preserves_source_circle_as_ellipse():
    stroke = _stroke(
        (NormalizedPoint(60, 40, width=40), NormalizedPoint(60.01, 40, width=40)),
        rgba=(0, 0, 0, 255),
    )
    a = np.asarray(_render(stroke, scale_x=2, scale_y=1))[:, :, 3]
    ys, xs = np.where(a > 128)
    assert xs.max() - xs.min() + 1 == pytest.approx(20, abs=1)
    assert ys.max() - ys.min() + 1 == pytest.approx(10, abs=1)
