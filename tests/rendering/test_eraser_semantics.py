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
    VisibilityState,
)
from rm_redraw.replay.schedule import progressive_distance_schedule

BACKGROUND = (12, 180, 60, 255)


def _stroke(
    stroke_id: str,
    group_id: str,
    rgba: tuple[int, int, int, int],
    points: tuple[tuple[float, float], ...],
    *,
    thickness: float = 12,
    tool_code: int | None = None,
    tool_name: str | None = None,
) -> NormalizedStroke:
    return NormalizedStroke(
        stroke_id=stroke_id,
        group_id=group_id,
        rgba=rgba,
        thickness_scale=thickness,
        points=tuple(NormalizedPoint(x, y) for x, y in points),
        tool_code=tool_code,
        tool_name=tool_name,
    )


def _eraser(
    stroke_id: str,
    group_id: str,
    points: tuple[tuple[float, float], ...],
    *,
    rgba: tuple[int, int, int, int] = (255, 255, 255, 255),
    thickness: float = 6,
    raw_width: float = 48,
) -> NormalizedStroke:
    result = _stroke(
        stroke_id,
        group_id,
        rgba,
        points,
        thickness=thickness,
        tool_code=6,
        tool_name="ERASER",
    )
    return replace(result, points=tuple(replace(p, width=raw_width) for p in result.points))


def _page(*strokes: NormalizedStroke) -> NormalizedPage:
    groups = tuple(
        NormalizedGroup(group_id)
        for group_id in dict.fromkeys(stroke.group_id for stroke in strokes)
    )
    return NormalizedPage(
        page_id="eraser-page",
        paper_size=(100, 100),
        groups=groups,
        strokes=strokes,
        compositing_order=tuple(group.group_id for group in groups),
        replay_order=tuple(stroke.stroke_id for stroke in strokes),
        replay_strategy="scene-order",
        replay_evidence="synthetic eraser fixture",
    )


def _render(page: NormalizedPage, visibility: VisibilityState | None = None):
    if visibility is None:
        return PillowRenderer().render_static(page, RenderOptions(background=BACKGROUND))
    return PillowRenderer().render(page, RenderOptions(background=BACKGROUND), visibility)


def test_eraser_clears_to_configured_background_instead_of_painting_white() -> None:
    ink = _stroke("ink", "layer", (0, 0, 0, 255), ((10, 50), (90, 50)))
    eraser = _eraser("eraser", "layer", ((50, 25), (50, 75)))

    image = _render(_page(ink, eraser))

    assert image.getpixel((50, 50)) == BACKGROUND


def test_eraser_clears_only_its_own_layer_and_reveals_lower_layer() -> None:
    lower = _stroke("lower", "lower", (255, 0, 0, 255), ((10, 50), (90, 50)))
    upper = _stroke("upper", "upper", (0, 0, 255, 255), ((10, 50), (90, 50)))
    eraser = _eraser("eraser", "upper", ((50, 25), (50, 75)))

    image = _render(_page(lower, upper, eraser))

    assert image.getpixel((50, 50)) == (255, 0, 0, 255)


def test_lower_layer_eraser_does_not_cut_upper_layer() -> None:
    lower = _stroke("lower", "lower", (255, 0, 0, 255), ((10, 50), (90, 50)))
    eraser = _eraser("eraser", "lower", ((50, 25), (50, 75)))
    upper = _stroke("upper", "upper", (0, 0, 255, 128), ((10, 50), (90, 50)))

    image = _render(_page(lower, eraser, upper))
    expected = _render(_page(upper))

    assert image.getpixel((50, 50)) == expected.getpixel((50, 50))


def test_later_ink_in_same_layer_draws_over_an_earlier_erasure() -> None:
    first = _stroke("first", "layer", (0, 0, 0, 255), ((10, 50), (90, 50)))
    eraser = _eraser("eraser", "layer", ((50, 25), (50, 75)))
    later = _stroke("later", "layer", (255, 0, 0, 128), ((25, 50), (75, 50)), thickness=4)

    image = _render(_page(first, eraser, later))
    expected = _render(_page(later))

    assert image.getpixel((50, 50)) == expected.getpixel((50, 50))


def test_eraser_dispatch_is_independent_of_recorded_colour() -> None:
    ink = _stroke("ink", "layer", (0, 0, 0, 255), ((10, 50), (90, 50)))
    white = _eraser("eraser", "layer", ((50, 25), (50, 75)))
    black = replace(white, rgba=(0, 0, 0, 255))

    white_image = _render(_page(ink, white))
    black_image = _render(_page(ink, black))

    assert white_image.tobytes() == black_image.tobytes()


def test_active_eraser_clears_only_its_distance_prefix() -> None:
    ink = _stroke("ink", "layer", (0, 0, 0, 255), ((10, 50), (90, 50)))
    eraser = _eraser("eraser", "layer", ((20, 50), (80, 50)))
    visibility = VisibilityState(
        completed_stroke_ids=frozenset({"ink"}),
        active_stroke_id="eraser",
        active_progress=0.5,
    )

    image = _render(_page(ink, eraser), visibility)

    assert image.getpixel((30, 50)) == BACKGROUND
    assert image.getpixel((70, 50)) == (0, 0, 0, 255)


def test_eraser_uses_raw_quarter_width_and_square_caps() -> None:
    ink = _stroke("ink", "layer", (0, 0, 0, 255), ((50, 20), (50, 80)), thickness=30)
    eraser = _eraser("eraser", "layer", ((50, 40), (50, 60)), thickness=50, raw_width=40)

    image = _render(_page(ink, eraser))

    assert image.getpixel((46, 50)) == BACKGROUND
    assert max(image.getpixel((43, 50))[:3]) < 5
    assert image.getpixel((50, 36)) == BACKGROUND
    assert max(image.getpixel((50, 32))[:3]) < 5


def test_progressive_replay_final_frame_matches_static_with_eraser() -> None:
    ink = _stroke("ink", "layer", (0, 0, 0, 255), ((10, 50), (90, 50)))
    eraser = _eraser("eraser", "layer", ((50, 25), (50, 75)))
    page = _page(ink, eraser)
    final_visibility = progressive_distance_schedule(
        page,
        fps=10,
        drawing_speed=100,
    )[-1].visibility

    final = _render(page, final_visibility)
    static = _render(page)

    assert final.getpixel((50, 50)) == BACKGROUND
    assert hashlib.sha256(final.tobytes()).digest() == hashlib.sha256(static.tobytes()).digest()


def test_eraser_width_ignores_thickness():
    ink = _stroke("ink", "layer", (0, 0, 0, 255), ((10, 50), (90, 50)), thickness=30)
    eraser = _eraser("eraser", "layer", ((50, 25), (50, 75)), raw_width=40, thickness=5)
    assert (
        _render(_page(ink, eraser)).tobytes()
        == _render(_page(ink, replace(eraser, thickness_scale=60))).tobytes()
    )


def test_degenerate_erasers_do_not_clear():
    ink = _stroke("ink", "layer", (0, 0, 0, 255), ((10, 50), (90, 50)))
    expected = _render(_page(ink)).tobytes()
    for coordinates in [((50, 50),), ((50, 50), (50, 50))]:
        assert _render(_page(ink, _eraser("eraser", "layer", coordinates))).tobytes() == expected


def test_variable_width_eraser_uses_local_width_and_progressive_endpoint():
    ink = _stroke("ink", "layer", (0, 0, 0, 255), ((10, 50), (90, 50)), thickness=60)
    eraser = _eraser("eraser", "layer", ((20, 50), (80, 50)), raw_width=8)
    eraser = replace(eraser, points=(eraser.points[0], replace(eraser.points[1], width=80)))
    image = _render(_page(ink, eraser))
    assert image.getpixel((25, 43)) == (0, 0, 0, 255)
    assert image.getpixel((75, 43)) == BACKGROUND
    partial = _render(_page(ink, eraser), VisibilityState(frozenset({"ink"}), "eraser", 0.5))
    assert partial.getpixel((45, 49)) == BACKGROUND
    assert partial.getpixel((75, 47)) == (0, 0, 0, 255)


def test_closed_eraser_path_leaves_interior_ink():
    ink = _stroke("ink", "layer", (0, 0, 0, 255), ((10, 50), (90, 50)), thickness=20)
    eraser = _eraser(
        "eraser", "layer", ((30, 30), (70, 30), (70, 70), (30, 70), (30, 30)), raw_width=32
    )
    image = _render(_page(ink, eraser))
    assert image.getpixel((50, 50)) == (0, 0, 0, 255)
    assert image.getpixel((30, 50)) == BACKGROUND


def test_variable_eraser_revealed_prefix_does_not_change_behind_tip():
    ink = _stroke("ink", "layer", (0, 0, 0, 255), ((0, 50), (100, 50)), thickness=80)
    eraser = _eraser("eraser", "layer", ((10, 50), (90, 50)), raw_width=8)
    eraser = replace(eraser, points=(eraser.points[0], replace(eraser.points[1], width=120)))
    page = _page(ink, eraser)
    first = _render(page, VisibilityState(frozenset({"ink"}), "eraser", 0.5))
    last = _render(page)
    assert first.crop((10, 20, 30, 80)).tobytes() == last.crop((10, 20, 30, 80)).tobytes()


def test_diagonal_square_eraser_cap_is_not_clipped_by_region():
    from PIL import Image

    from rm_redraw.rendering.pillow import _erase_stroke

    for widths in ([40, 40], [40, 48]):
        image = Image.new("RGBA", (100, 100), (0, 0, 0, 255))
        _erase_stroke(image, [(40, 40), (60, 60)], widths)
        assert image.getpixel((15, 40))[3] < 5


def test_duplicate_endpoints_do_not_rotate_eraser_caps():
    from PIL import Image

    from rm_redraw.rendering.pillow import _erase_stroke

    expected = Image.new("RGBA", (100, 100), (0, 0, 0, 255))
    _erase_stroke(expected, [(40, 40), (60, 60)], [40, 40])
    for coords in [[(40, 40), (40, 40), (60, 60)], [(40, 40), (60, 60), (60, 60)]]:
        image = Image.new("RGBA", (100, 100), (0, 0, 0, 255))
        _erase_stroke(image, coords, [40] * len(coords))
        assert image.tobytes() == expected.tobytes()
