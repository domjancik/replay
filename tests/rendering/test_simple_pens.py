from dataclasses import replace

import numpy as np
import pytest

from rm_redraw.rendering import PillowRenderer
from rm_redraw.rendering.types import (
    NormalizedGroup,
    NormalizedPage,
    NormalizedPoint,
    NormalizedStroke,
    RenderOptions,
    VisibilityState,
)


def _page(tool=17, points=None, thickness=2):
    stroke = NormalizedStroke(
        "line",
        "ink",
        (0, 0, 0, 255),
        thickness,
        points or (NormalizedPoint(30, 60, width=48), NormalizedPoint(130, 60, width=48)),
        tool_code=tool,
    )
    return NormalizedPage(
        "p",
        (160, 120),
        (NormalizedGroup("ink"),),
        (stroke,),
        ("ink",),
        ("line",),
        "scene-order",
        "synthetic",
    )


@pytest.mark.parametrize("tool", [17, 18])
def test_native_simple_width_is_quarter_raw_channel_and_thickness_independent(tool):
    renderer = PillowRenderer()
    small = renderer.render_static(_page(tool, thickness=0.5), RenderOptions())
    large = renderer.render_static(_page(tool, thickness=8), RenderOptions())
    assert small.tobytes() == large.tobytes()
    darkness = 1 - np.asarray(small)[:, 80, 0].astype(float) / 255
    assert darkness.sum() == pytest.approx(12, abs=0.6)


@pytest.mark.parametrize("tool", [17, 18])
def test_native_single_point_simple_pen_is_blank(tool):
    image = PillowRenderer().render_static(
        _page(tool, (NormalizedPoint(60, 60, width=48),)), RenderOptions()
    )
    assert np.asarray(image).min() == 255


def test_fineliner_coincident_pair_is_dot_but_highlighter_pair_is_blank():
    points = (NormalizedPoint(60, 60, width=48),) * 2
    fineliner = PillowRenderer().render_static(_page(17, points), RenderOptions())
    highlighter = PillowRenderer().render_static(_page(18, points), RenderOptions())
    assert fineliner.getpixel((60, 60))[0] == 0
    assert np.asarray(highlighter).min() == 255


def test_fineliner_round_and_highlighter_butt_caps():
    renderer = PillowRenderer()
    fine = renderer.render_static(_page(17), RenderOptions())
    high = renderer.render_static(_page(18), RenderOptions())
    assert fine.getpixel((26, 60))[0] < 20
    assert high.getpixel((26, 60))[0] == 255


@pytest.mark.parametrize("tool", [16, 17, 18])
def test_simple_progressive_prefix_stable_and_final_identical(tool):
    page = _page(tool)
    renderer = PillowRenderer()
    options = RenderOptions()
    a = renderer.render(
        page, options, VisibilityState(active_stroke_id="line", active_progress=0.5)
    )
    b = renderer.render(
        page, options, VisibilityState(active_stroke_id="line", active_progress=0.8)
    )
    assert a.crop((0, 0, 60, 120)).tobytes() == b.crop((0, 0, 60, 120)).tobytes()
    final = renderer.render(
        page, options, VisibilityState(active_stroke_id="line", active_progress=1)
    )
    assert final.tobytes() == renderer.render_static(page, options).tobytes()


def test_highlighter_darkens_existing_ink_without_recoloring_black_or_transparent_black():
    page = _page(18)
    base = replace(
        page.strokes[0],
        stroke_id="base",
        tool_code=17,
        points=(NormalizedPoint(80, 20, width=48), NormalizedPoint(80, 100, width=48)),
    )
    high = replace(page.strokes[0], rgba=(254, 253, 96, 255))
    page = replace(page, strokes=(base, high), replay_order=("base", "line"))
    image = PillowRenderer().render_static(page, RenderOptions())
    assert image.getpixel((80, 60))[:3] == (0, 0, 0)
    assert image.getpixel((50, 60))[:3] == (254, 253, 96)


def test_marker_calibrated_envelope_uses_width_not_thickness():
    renderer = PillowRenderer()
    a = renderer.render_static(_page(16, thickness=0.5), RenderOptions())
    b = renderer.render_static(_page(16, thickness=8), RenderOptions())
    assert a.tobytes() == b.tobytes()
    assert (1 - np.asarray(a)[:, 80, 0] / 255).sum() == pytest.approx(9, abs=0.6)


@pytest.mark.parametrize(
    "points",
    [
        (NormalizedPoint(60, 60, width=48),),
        (NormalizedPoint(60, 60, width=48),) * 2,
        (NormalizedPoint(30, 60, width=4), NormalizedPoint(130, 60, width=4)),
    ],
)
def test_marker_captured_degenerate_and_minimum_width_controls_are_blank(points):
    image = PillowRenderer().render_static(_page(16, points), RenderOptions())
    assert np.asarray(image).min() == 255


def test_variable_width_fineliner_keeps_native_first_point_width():
    points = (NormalizedPoint(30, 60, width=8), NormalizedPoint(130, 60, width=80))
    page = _page(17, points)
    expected = _page(17, tuple(replace(p, width=points[0].width) for p in points))
    renderer = PillowRenderer()
    for progress in [0.2, 0.8, 1.0]:
        state = VisibilityState(active_stroke_id="line", active_progress=progress)
        assert (
            renderer.render(page, RenderOptions(), state).tobytes()
            == renderer.render(expected, RenderOptions(), state).tobytes()
        )
