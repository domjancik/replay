from __future__ import annotations

import hashlib
from dataclasses import replace

from rm_redraw.rendering.pillow import PillowRenderer
from rm_redraw.rendering.types import (
    NormalizedGroup,
    NormalizedPage,
    NormalizedPoint,
    NormalizedStroke,
    RenderOptions,
    Viewport,
    VisibilityState,
)


def _page() -> NormalizedPage:
    return NormalizedPage(
        page_id="synthetic-page",
        paper_size=(100, 80),
        groups=(
            NormalizedGroup("lower"),
            NormalizedGroup("upper"),
        ),
        strokes=(
            NormalizedStroke(
                stroke_id="lower-stroke",
                group_id="lower",
                rgba=(255, 0, 0, 128),
                thickness_scale=10,
                points=(NormalizedPoint(10, 40), NormalizedPoint(90, 40)),
            ),
            NormalizedStroke(
                stroke_id="upper-stroke",
                group_id="upper",
                rgba=(0, 0, 255, 255),
                thickness_scale=10,
                points=(NormalizedPoint(50, 5), NormalizedPoint(50, 75)),
            ),
        ),
        compositing_order=("lower", "upper"),
        replay_order=("upper-stroke", "lower-stroke"),
        replay_strategy="scene-order",
        replay_evidence="synthetic fixture",
    )


def test_revealing_lower_layer_does_not_cover_visible_upper_layer() -> None:
    renderer = PillowRenderer()
    image = renderer.render(
        _page(),
        RenderOptions(),
        VisibilityState(frozenset({"upper-stroke", "lower-stroke"})),
    )

    assert image.getpixel((50, 40)) == (0, 0, 255, 255)


def test_hidden_layer_is_not_drawn_even_when_its_stroke_is_completed() -> None:
    page = _page()
    page = replace(
        page,
        groups=(page.groups[0], replace(page.groups[1], visible=False)),
    )

    image = PillowRenderer().render(
        page,
        RenderOptions(),
        VisibilityState(frozenset({"upper-stroke", "lower-stroke"})),
    )

    assert image.getpixel((50, 40)) == (255, 127, 127, 255)


def test_renderer_uses_a_fixed_explicit_viewport() -> None:
    image = PillowRenderer().render(
        _page(),
        RenderOptions(viewport=Viewport(240, 120)),
        VisibilityState(frozenset({"lower-stroke"})),
    )

    assert image.size == (240, 120)


def test_active_stroke_progress_renders_only_distance_prefix() -> None:
    image = PillowRenderer().render(
        _page(),
        RenderOptions(),
        VisibilityState(active_stroke_id="lower-stroke", active_progress=0.5),
    )

    assert image.getpixel((45, 40))[3] > 0
    assert image.getpixel((70, 40)) == (255, 255, 255, 255)


def test_partial_translucent_stroke_is_rerendered_from_state() -> None:
    renderer = PillowRenderer()
    partial_state = VisibilityState(active_stroke_id="lower-stroke", active_progress=0.5)

    first = renderer.render(_page(), RenderOptions(), partial_state)
    renderer.render(_page(), RenderOptions(), VisibilityState(frozenset({"lower-stroke"})))
    second = renderer.render(_page(), RenderOptions(), partial_state)

    assert hashlib.sha256(first.tobytes()).digest() == hashlib.sha256(second.tobytes()).digest()
