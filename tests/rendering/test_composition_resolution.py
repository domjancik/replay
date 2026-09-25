"""Reduce textured pages after compositing, so shared paper holes survive."""

from dataclasses import replace

import pytest
from PIL import Image

from rm_redraw.rendering import PillowRenderer
from rm_redraw.rendering.types import (
    NormalizedGroup,
    NormalizedPage,
    NormalizedPoint,
    NormalizedStroke,
    RenderOptions,
    Viewport,
    VisibilityState,
)


def model():
    strokes = tuple(
        NormalizedStroke(
            str(i),
            "ink",
            (0, 0, 0, 255),
            4,
            (NormalizedPoint(8, 20, 128, 0, 0, 48), NormalizedPoint(92, 20, 128, 0, 0, 48)),
            14,
        )
        for i in range(9)
    )
    strokes += (replace(strokes[0], stroke_id="translucent", rgba=(150, 20, 40, 90)),)
    return NormalizedPage(
        "p",
        (100, 50),
        (NormalizedGroup("ink"),),
        strokes,
        ("ink",),
        tuple(s.stroke_id for s in strokes),
        "scene-order",
        "synthetic",
    )


@pytest.mark.parametrize("background", [(255, 255, 255, 255), (0, 0, 0, 0)])
def test_textured_static_reduces_after_ordered_composition(background):
    page = model()
    r = PillowRenderer()
    full = r.render_static(page, RenderOptions(background=background))
    actual = r.render_static(page, RenderOptions(viewport=Viewport(50, 25), background=background))
    assert actual.tobytes() == full.resize((50, 25), Image.Resampling.BOX).tobytes()


def test_reduced_progress_cache_matches_source_composition_and_final():
    page = model()
    options = RenderOptions(viewport=Viewport(50, 25))
    renderer = PillowRenderer()
    for count in (1, 5, 10, 3):
        state = VisibilityState(frozenset(page.replay_order[:count]))
        expected = (
            PillowRenderer()
            .render(page, RenderOptions(), state)
            .resize((50, 25), Image.Resampling.BOX)
        )
        actual = renderer.render(page, options, state)
        assert actual.tobytes() == expected.tobytes()
    final = renderer.render(page, options, VisibilityState(frozenset(page.replay_order)))
    assert final.tobytes() == renderer.render_static(page, options).tobytes()


@pytest.mark.parametrize("progress", [0.25, 0.7, 1.0])
def test_reduced_mixed_layers_eraser_and_active_reveal(progress):
    page = model()
    first = page.strokes[0]
    strokes = page.strokes + (
        replace(first, stroke_id="erase", tool_code=6),
        replace(first, stroke_id="upper", group_id="upper", tool_code=17, rgba=(40, 100, 200, 140)),
    )
    page = replace(
        page,
        groups=(NormalizedGroup("ink"), NormalizedGroup("upper")),
        strokes=strokes,
        compositing_order=("ink", "upper"),
        replay_order=tuple(s.stroke_id for s in strokes),
    )
    options = RenderOptions(viewport=Viewport(43, 19))
    # Arbitrary visibility exercises the nonprefix path and ordered layer erasure.
    state = VisibilityState(frozenset(("0", "2", "erase")), "upper", progress)
    expected = (
        PillowRenderer().render(page, RenderOptions(), state).resize((43, 19), Image.Resampling.BOX)
    )
    assert PillowRenderer().render(page, options, state).tobytes() == expected.tobytes()


@pytest.mark.parametrize("hidden", [True, False])
def test_invisible_texture_cannot_change_visible_rasterization(hidden):
    page = model()
    visible = replace(
        page.strokes[0],
        tool_code=17,
        points=(NormalizedPoint(8, 13.2, width=11), NormalizedPoint(92, 36.9, width=11)),
    )
    page = replace(page, strokes=(visible,), replay_order=(visible.stroke_id,))
    options = RenderOptions(viewport=Viewport(43, 19))
    baseline = PillowRenderer().render_static(page, options)
    invisible = replace(page.strokes[0], stroke_id="hidden-pencil", group_id="other", tool_code=14)
    with_invisible = replace(
        page,
        strokes=page.strokes + (invisible,),
        groups=page.groups + (NormalizedGroup("other", visible=not hidden),),
        compositing_order=("ink", "other") if hidden else ("ink",),
    )
    assert PillowRenderer().render_static(with_invisible, options).tobytes() == baseline.tobytes()
