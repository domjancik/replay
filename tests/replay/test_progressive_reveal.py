from __future__ import annotations

from PIL import ImageChops

from rm_redraw.rendering.geometry import prefix_points
from rm_redraw.rendering.pillow import PillowRenderer
from rm_redraw.rendering.types import (
    NormalizedGroup,
    NormalizedPage,
    NormalizedPoint,
    NormalizedStroke,
    RenderOptions,
    VisibilityState,
)


def _stroke(points: tuple[NormalizedPoint, ...]) -> NormalizedStroke:
    return NormalizedStroke(
        stroke_id="directional",
        group_id="ink",
        rgba=(0, 0, 0, 255),
        thickness_scale=4,
        points=points,
    )


def _page(stroke: NormalizedStroke) -> NormalizedPage:
    return NormalizedPage(
        page_id="directional-reveal",
        paper_size=(32, 24),
        groups=(NormalizedGroup("ink"),),
        strokes=(stroke,),
        compositing_order=("ink",),
        replay_order=(stroke.stroke_id,),
        replay_strategy="scene-order",
        replay_evidence="synthetic point-order fixture",
    )


def test_sparse_uneven_points_interpolate_by_distance() -> None:
    stroke = _stroke(
        (
            NormalizedPoint(0, 0, pressure=10, speed=2, width=3),
            NormalizedPoint(20, 0, pressure=20, speed=4, width=5),
            NormalizedPoint(20, 4, pressure=40, speed=8, width=9),
        )
    )

    prefix = prefix_points(stroke, 0.875)

    assert prefix[:2] == stroke.points[:2]
    assert prefix[-1] == NormalizedPoint(
        20,
        1,
        pressure=25,
        speed=5,
        width=6,
    )


def test_reverse_and_self_crossing_reveal_preserves_recorded_sequence() -> None:
    stroke = _stroke(
        (
            NormalizedPoint(0, 0),
            NormalizedPoint(10, 0),
            NormalizedPoint(0, 0),
            NormalizedPoint(0, 10),
        )
    )

    reverse_prefix = prefix_points(stroke, 0.5)
    crossing_prefix = prefix_points(stroke, 5 / 6)

    assert [(point.x, point.y) for point in reverse_prefix] == [
        (0, 0),
        (10, 0),
        (5, 0),
    ]
    assert [(point.x, point.y) for point in crossing_prefix] == [
        (0, 0),
        (10, 0),
        (0, 0),
        (0, 5),
    ]


def test_advancing_cap_keeps_completed_trail_pixels_stable() -> None:
    stroke = _stroke((NormalizedPoint(4, 12), NormalizedPoint(28, 12)))
    page = _page(stroke)
    renderer = PillowRenderer()
    earlier = renderer.render(
        page,
        RenderOptions(),
        VisibilityState(active_stroke_id=stroke.stroke_id, active_progress=0.5),
    )
    later = renderer.render(
        page,
        RenderOptions(),
        VisibilityState(active_stroke_id=stroke.stroke_id, active_progress=0.75),
    )

    stable_trail = (0, 0, 10, 24)
    assert ImageChops.difference(
        earlier.crop(stable_trail).convert("RGB"),
        later.crop(stable_trail).convert("RGB"),
    ).getbbox() is None
    assert ImageChops.difference(
        earlier.convert("RGB"), later.convert("RGB")
    ).getbbox() is not None
