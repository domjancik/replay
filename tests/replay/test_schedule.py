from __future__ import annotations

from rm_redraw.rendering.types import (
    NormalizedGroup,
    NormalizedPage,
    NormalizedPoint,
    NormalizedStroke,
)
from rm_redraw.replay.schedule import (
    progressive_distance_schedule,
    progressive_stroke_schedule,
    stroke_step_schedule,
)


def _page() -> NormalizedPage:
    return NormalizedPage(
        page_id="schedule-page",
        paper_size=(100, 80),
        groups=(NormalizedGroup("ink"),),
        strokes=(
            NormalizedStroke(
                stroke_id="first",
                group_id="ink",
                rgba=(0, 0, 0, 255),
                thickness_scale=4,
                points=(NormalizedPoint(0, 0), NormalizedPoint(10, 0)),
            ),
            NormalizedStroke(
                stroke_id="second",
                group_id="ink",
                rgba=(0, 0, 0, 255),
                thickness_scale=4,
                points=(NormalizedPoint(0, 0), NormalizedPoint(30, 0)),
            ),
        ),
        compositing_order=("ink",),
        replay_order=("first", "second"),
        replay_strategy="scene-order",
        replay_evidence="synthetic fixture",
    )


def test_stroke_step_schedule_reveals_replay_order() -> None:
    frames = stroke_step_schedule(_page())

    assert [frame.visibility.completed_stroke_ids for frame in frames] == [
        frozenset({"first"}),
        frozenset({"first", "second"}),
    ]


def test_distance_schedule_uses_distance_for_frame_count_and_progress() -> None:
    frames = progressive_distance_schedule(_page(), fps=2, drawing_speed=10)

    second_active = [
        frame.visibility for frame in frames if frame.visibility.active_stroke_id == "second"
    ]
    assert [state.active_progress for state in second_active] == [1 / 6, 2 / 6, 3 / 6, 4 / 6, 5 / 6]
    assert frames[-1].visibility.completed_stroke_ids == frozenset({"first", "second"})


def test_constant_duration_schedule_uses_same_duration_for_each_stroke() -> None:
    frames = progressive_stroke_schedule(_page(), fps=4, seconds_per_stroke=0.5)

    active = [frame.visibility for frame in frames if frame.visibility.active_stroke_id]
    assert [state.active_progress for state in active] == [0.5, 0.5]
    assert frames[-1].visibility.completed_stroke_ids == frozenset({"first", "second"})
