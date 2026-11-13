from dataclasses import replace

import pytest

from rm_redraw.rendering import PillowRenderer, pillow
from rm_redraw.rendering.types import (
    NormalizedGroup,
    NormalizedPage,
    NormalizedPoint,
    NormalizedStroke,
    RenderOptions,
    Viewport,
    VisibilityState,
)


def _page():
    def stroke(sid, group, y, rgba, tool=17):
        return NormalizedStroke(
            sid,
            group,
            rgba,
            2,
            (
                NormalizedPoint(10, y, width=32, pressure=128, speed=16, direction=0),
                NormalizedPoint(70, y, width=32, pressure=128, speed=16, direction=0),
            ),
            tool_code=tool,
        )

    strokes = (
        stroke("black", "lower", 25, (0, 0, 0, 255)),
        stroke("white", "lower", 26, (255, 255, 255, 255)),
        stroke("red", "upper", 25, (220, 0, 0, 128)),
        stroke("erase", "upper", 26, (0, 0, 0, 255), 6),
        stroke("later", "upper", 29, (0, 0, 180, 190)),
    )
    return NormalizedPage(
        "p",
        (80, 60),
        (NormalizedGroup("lower"), NormalizedGroup("upper")),
        strokes,
        ("lower", "upper"),
        tuple(s.stroke_id for s in strokes),
        "scene-order",
        "synthetic",
    )


def _reference(page, options, state):
    # Project exactly the visible geometry and render via independent static path.
    strokes = []
    for s in page.strokes:
        if s.stroke_id in state.completed_stroke_ids:
            strokes.append(s)
        elif s.stroke_id == state.active_stroke_id:
            points = pillow.prefix_points(s, state.active_progress)
            if points:
                strokes.append(replace(s, points=points))
    return PillowRenderer().render_static(replace(page, strokes=tuple(strokes)), options)


def test_prefix_cache_avoids_redrawing_completed_strokes(monkeypatch):
    page = _page()
    actual = pillow._draw_stroke
    calls = []

    def count(*args, **kwargs):
        calls.append(args[2].stroke_id)
        return actual(*args, **kwargs)

    monkeypatch.setattr(pillow, "_draw_stroke", count)
    renderer = PillowRenderer()
    for i in range(1, len(page.strokes) + 1):
        renderer.render(page, RenderOptions(), VisibilityState(frozenset(page.replay_order[:i])))
    assert calls == list(page.replay_order)


def test_cached_layers_alpha_white_highlights_and_eraser_match_fresh_static():
    page = _page()
    options = RenderOptions()
    renderer = PillowRenderer()
    for i, sid in enumerate(page.replay_order):
        for fraction in [0.2, 0.75, 1]:
            state = VisibilityState(frozenset(page.replay_order[:i]), sid, fraction)
            assert (
                renderer.render(page, options, state).tobytes()
                == _reference(page, options, state).tobytes()
            )
    all_visible = VisibilityState(frozenset(page.replay_order))
    final = renderer.render(page, options, all_visible)
    assert final.tobytes() == renderer.render_static(page, options).tobytes()
    # Callers own returned images; modifying one cannot poison cached canvases.
    final.paste((255, 0, 255, 255), (0, 0, 80, 60))
    assert (
        renderer.render(page, options, all_visible).tobytes()
        == renderer.render_static(page, options).tobytes()
    )


@pytest.mark.parametrize(
    "states",
    [
        [
            VisibilityState(frozenset(("black", "white", "red"))),
            VisibilityState(frozenset(("black",))),
        ],
        [VisibilityState(frozenset(("red",))), VisibilityState(frozenset(("black", "white")))],
        [
            VisibilityState(frozenset(("black",)), "later", 0.8),
            VisibilityState(frozenset(("black",)), "white", 0.2),
        ],
        [
            VisibilityState(frozenset(("black",)), "white", 0.8),
            VisibilityState(frozenset(("black",)), "white", 0.2),
        ],
    ],
)
def test_nonmonotone_or_nonprefix_visibility_remains_exact(states):
    page = _page()
    renderer = PillowRenderer()
    options = RenderOptions()
    for state in states:
        assert (
            renderer.render(page, options, state).tobytes()
            == _reference(page, options, state).tobytes()
        )


def test_page_identity_and_options_invalidate_cached_pixels():
    original = _page()
    renderer = PillowRenderer()
    state = VisibilityState(frozenset(original.replay_order))
    for page, options in [
        (original, RenderOptions()),
        (
            replace(
                original, strokes=tuple(replace(s, rgba=(0, 220, 0, 128)) for s in original.strokes)
            ),
            RenderOptions(),
        ),
        (original, RenderOptions(viewport=Viewport(40, 30), background=(120, 120, 120, 255))),
        (original, RenderOptions()),
    ]:
        assert (
            renderer.render(page, options, state).tobytes()
            == renderer.render_static(page, options).tobytes()
        )


def test_texture_and_darken_cache_matches_stateless_at_each_progress():
    page = _page()
    strokes = list(page.strokes)
    strokes[0] = replace(strokes[0], tool_code=14)
    strokes[1] = replace(strokes[1], tool_code=18, rgba=(254, 253, 96, 255))
    page = replace(page, strokes=tuple(strokes))
    renderer = PillowRenderer()
    options = RenderOptions()
    for i, sid in enumerate(page.replay_order):
        for progress in [0.1, 0.5, 0.9, 1]:
            state = VisibilityState(frozenset(page.replay_order[:i]), sid, progress)
            assert (
                renderer.render(page, options, state).tobytes()
                == renderer._render_uncached(page, options, state).tobytes()
            )


def test_hidden_groups_and_out_of_order_layer_strokes_do_not_change_pixels():
    page = _page()
    page = replace(page, groups=(NormalizedGroup("lower", False), NormalizedGroup("upper")))
    renderer = PillowRenderer()
    options = RenderOptions()
    for ids in [("black",), ("black", "red"), ("black", "red", "later"), page.replay_order]:
        state = VisibilityState(frozenset(ids))
        assert (
            renderer.render(page, options, state).tobytes()
            == renderer._render_uncached(page, options, state).tobytes()
        )


def test_interleaved_layer_cache_reuses_completed_ink(monkeypatch):
    page = _page()
    actual = pillow._draw_stroke
    calls = []

    def count(*args, **kwargs):
        calls.append(args[2].stroke_id)
        return actual(*args, **kwargs)

    monkeypatch.setattr(pillow, "_draw_stroke", count)
    renderer = PillowRenderer()
    for progress in (0.2, 0.4, 0.8):
        renderer.render(
            page, RenderOptions(), VisibilityState(frozenset({"red"}), "black", progress)
        )
    assert calls.count("red") == 1
    assert calls.count("black") == 3


@pytest.mark.parametrize("viewport", [Viewport(40, 30), Viewport(160, 120)])
def test_interleaved_texture_eraser_and_backwards_frames_match_reference(viewport):
    page = _page()
    strokes = list(page.strokes)
    strokes[0] = replace(strokes[0], tool_code=14)
    strokes[1] = replace(strokes[1], tool_code=18, rgba=(254, 253, 96, 255))
    page = replace(page, strokes=tuple(strokes))
    renderer = PillowRenderer()
    options = RenderOptions(viewport=viewport)
    order = ["red", "black", "erase", "white", "later"]
    states = [
        VisibilityState(frozenset(order[:i]), sid, progress)
        for i, sid in enumerate(order)
        for progress in (0.2, 0.8, 1)
    ]
    for state in states + list(reversed(states)):
        assert (
            renderer.render(page, options, state).tobytes()
            == renderer._render_uncached(page, options, state).tobytes()
        )
    assert (
        renderer.render(page, options, VisibilityState(frozenset(order))).tobytes()
        == renderer.render_static(page, options).tobytes()
    )


def test_interleaved_cache_budget_falls_back_without_allocating(monkeypatch):
    renderer = PillowRenderer()
    sentinel = object()
    monkeypatch.setattr(renderer, "_render_uncached", lambda *args: sentinel)
    assert (
        renderer._render_interleaved(
            _page(),
            RenderOptions(viewport=Viewport(4096, 4096)),
            VisibilityState(frozenset({"red"})),
        )
        is sentinel
    )
    assert renderer._layer_cache is None


def test_interleaved_cache_drops_old_page_on_prefix_switch():
    page = _page()
    renderer = PillowRenderer()
    renderer.render(page, RenderOptions(), VisibilityState(frozenset({"red"})))
    assert renderer._layer_cache is not None
    replacement = replace(page, page_id="replacement")
    renderer.render(replacement, RenderOptions(), VisibilityState())
    assert renderer._layer_cache is None
