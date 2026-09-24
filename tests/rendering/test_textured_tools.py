from dataclasses import replace

import numpy as np
import pytest

from rm_redraw.rendering.pillow import PillowRenderer
from rm_redraw.rendering.types import (
    NormalizedGroup,
    NormalizedPage,
    NormalizedPoint,
    NormalizedStroke,
    RenderOptions,
    VisibilityState,
)


def page(tool=14, pressure=128, direction=0):
    stroke = NormalizedStroke(
        "grain",
        "layer",
        (20, 40, 70, 220),
        12,
        (
            NormalizedPoint(15, 40, pressure, 0, direction, 48),
            NormalizedPoint(185, 40, pressure, 0, direction, 48),
        ),
        tool,
    )
    return NormalizedPage(
        "texture",
        (200, 80),
        (NormalizedGroup("layer"),),
        (stroke,),
        ("layer",),
        ("grain",),
        "scene-order",
        "synthetic",
    )


@pytest.mark.parametrize("tool", [0, 1, 7, 12, 13, 14])
def test_texture_has_grain_and_pressure_response(tool):
    renderer = PillowRenderer()
    low = np.asarray(renderer.render_static(page(tool, 32), RenderOptions()))
    high = np.asarray(renderer.render_static(page(tool, 224), RenderOptions()))
    assert np.unique(high[38:42, 30:160, 0]).size > 8
    assert high[:, :, :3].mean() < low[:, :, :3].mean()


@pytest.mark.parametrize("tool", [12, 14])
def test_texture_prefix_stays_fixed_and_final_matches(tool):
    renderer = PillowRenderer()
    model = page(tool)
    a = renderer.render(
        model, RenderOptions(), VisibilityState(active_stroke_id="grain", active_progress=0.4)
    )
    b = renderer.render(
        model, RenderOptions(), VisibilityState(active_stroke_id="grain", active_progress=0.8)
    )
    assert a.crop((0, 0, 65, 80)).tobytes() == b.crop((0, 0, 65, 80)).tobytes()
    assert a.getpixel((140, 40)) == (255, 255, 255, 255)
    assert (
        renderer.render(
            model, RenderOptions(), VisibilityState(active_stroke_id="grain", active_progress=1)
        ).tobytes()
        == renderer.render_static(model, RenderOptions()).tobytes()
    )


def test_brush_direction_wraps_and_changes_nib():
    renderer = PillowRenderer()
    def render(angle):
        return renderer.render_static(page(12, direction=angle), RenderOptions()).tobytes()
    assert render(0) == render(255)
    assert render(0) != render(64)


def test_texture_self_crossing_does_not_reveal_future_arm():
    model = page()
    points = tuple(
        NormalizedPoint(x, y, 128, 0, 0, 48) for x, y in [(20, 20), (150, 60), (150, 20), (20, 60)]
    )
    model = replace(model, strokes=(replace(model.strokes[0], points=points),))
    image = PillowRenderer().render(
        model, RenderOptions(), VisibilityState(active_stroke_id="grain", active_progress=0.2)
    )
    assert image.getpixel((140, 23)) == (255, 255, 255, 255)
