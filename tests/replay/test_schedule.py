from __future__ import annotations

from dataclasses import replace

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


def _interleaved_layers_page() -> NormalizedPage:
    """Global replay order deliberately alternates between two compositing layers."""
    points = (NormalizedPoint(0, 0), NormalizedPoint(10, 0))
    return NormalizedPage(
        page_id="interleaved-layers",
        paper_size=(100, 80),
        groups=(NormalizedGroup("lower"), NormalizedGroup("upper")),
        strokes=(
            NormalizedStroke("lower-late", "lower", (0, 0, 0, 255), 4, points),
            NormalizedStroke("lower-early", "lower", (0, 0, 0, 255), 4, points),
            NormalizedStroke("upper-early", "upper", (0, 0, 0, 255), 4, points),
            NormalizedStroke("upper-late", "upper", (0, 0, 0, 255), 4, points),
        ),
        compositing_order=("lower", "upper"),
        replay_order=("upper-early", "lower-late", "upper-late", "lower-early"),
        replay_strategy="crdt-order",
        replay_evidence="synthetic interleaved global order",
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


def test_stroke_step_schedule_finishes_lower_layer_before_higher_layer() -> None:
    page = _interleaved_layers_page()

    frames = stroke_step_schedule(page)

    assert [frame.visibility.completed_stroke_ids for frame in frames] == [
        frozenset({"lower-late"}),
        frozenset({"lower-late", "lower-early"}),
        frozenset({"lower-late", "lower-early", "upper-early"}),
        frozenset({"lower-late", "lower-early", "upper-early", "upper-late"}),
    ]
    assert page.compositing_order == ("lower", "upper")


def test_progressive_schedules_keep_global_order_within_each_layer() -> None:
    page = _interleaved_layers_page()

    duration_frames = progressive_stroke_schedule(page, fps=2, seconds_per_stroke=1)
    distance_frames = progressive_distance_schedule(page, fps=2, drawing_speed=10)

    expected = ["lower-late", "lower-early", "upper-early", "upper-late"]
    assert [
        frame.visibility.active_stroke_id
        for frame in duration_frames
        if frame.visibility.active_stroke_id is not None
    ] == expected
    assert [
        frame.visibility.active_stroke_id
        for frame in distance_frames
        if frame.visibility.active_stroke_id is not None
    ] == expected


def test_schedules_omit_strokes_from_hidden_layers() -> None:
    page = _interleaved_layers_page()
    page = replace(page, groups=(page.groups[0], replace(page.groups[1], visible=False)))

    step_frames = stroke_step_schedule(page)
    duration_frames = progressive_stroke_schedule(page, fps=2, seconds_per_stroke=1)
    distance_frames = progressive_distance_schedule(page, fps=2, drawing_speed=10)

    assert step_frames[-1].visibility.completed_stroke_ids == frozenset(
        {"lower-late", "lower-early"}
    )
    assert [
        frame.visibility.active_stroke_id
        for frame in duration_frames
        if frame.visibility.active_stroke_id is not None
    ] == ["lower-late", "lower-early"]
    assert [
        frame.visibility.active_stroke_id
        for frame in distance_frames
        if frame.visibility.active_stroke_id is not None
    ] == ["lower-late", "lower-early"]
