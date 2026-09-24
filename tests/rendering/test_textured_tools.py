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
    if tool != 12:  # Native current brush has solid interiors, unlike pencil grain.
        assert np.unique(high[38:42, 30:160, 0]).size > (1 if tool in {13, 14} else 8)
    assert high[:, :, :3].mean() < low[:, :, :3].mean()


@pytest.mark.parametrize("tool", [12, 13, 14])
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


@pytest.mark.parametrize("tool", [12, 13, 14])
def test_current_textured_degenerate_paths_are_unpainted(tool):
    model = page(tool)
    for points in [(model.strokes[0].points[0],), (model.strokes[0].points[0],) * 2]:
        fixture = replace(model, strokes=(replace(model.strokes[0], points=points),))
        image = np.asarray(PillowRenderer().render_static(fixture, RenderOptions()))
        assert np.all(image == 255)


def test_current_pencil_and_mechanical_share_native_profile():
    r = PillowRenderer()
    assert (
        r.render_static(page(13), RenderOptions()).tobytes()
        == r.render_static(page(14), RenderOptions()).tobytes()
    )


def test_current_brush_speed_reduces_ink_and_low_pressure_has_no_ink():
    r = PillowRenderer()
    model = page(12)
    fast = replace(
        model,
        strokes=(
            replace(
                model.strokes[0],
                points=tuple(replace(p, speed=240) for p in model.strokes[0].points),
            ),
        ),
    )
    assert (
        np.asarray(r.render_static(fast, RenderOptions()))[:, :, :3].mean()
        > np.asarray(r.render_static(model, RenderOptions()))[:, :, :3].mean()
    )
    low = page(12, 16)
    low = replace(
        low,
        strokes=(
            replace(
                low.strokes[0], points=tuple(replace(p, width=24) for p in low.strokes[0].points)
            ),
        ),
    )
    assert np.all(np.asarray(r.render_static(low, RenderOptions())) == 255)


@pytest.mark.parametrize("tool", [13, 14])
def test_current_pencil_grain_contains_clear_paper_and_dark_grains(tool):
    model = page(tool, 128)
    model = replace(model, strokes=(replace(model.strokes[0], rgba=(0, 0, 0, 255)),))
    pixels = np.asarray(PillowRenderer().render_static(model, RenderOptions()))[38:42, 30:160, 0]
    assert np.mean(pixels < 30) > 0.1
    assert np.mean(pixels > 245) > 0.1
