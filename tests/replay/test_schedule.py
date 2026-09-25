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


def test_stroke_step_schedule_supports_video_holds() -> None:
    frames = stroke_step_schedule(
        _page(),
        fps=2,
        initial_pause_seconds=0.5,
        pause_between_strokes_seconds=0.5,
        final_hold_seconds=0.5,
    )

    assert [frame.visibility.completed_stroke_ids for frame in frames] == [
        frozenset(),
        frozenset({"first"}),
        frozenset({"first"}),
        frozenset({"first", "second"}),
        frozenset({"first", "second"}),
    ]
    assert [frame.time_seconds for frame in frames] == [index / 2 for index in range(5)]


def test_distance_schedule_uses_distance_for_frame_count_and_progress() -> None:
    frames = progressive_distance_schedule(_page(), fps=2, drawing_speed=10)

    second_active = [
        frame.visibility for frame in frames if frame.visibility.active_stroke_id == "second"
    ]
    assert [state.active_progress for state in second_active] == [1 / 6, 2 / 6, 3 / 6, 4 / 6, 5 / 6]
    assert frames[-1].visibility.completed_stroke_ids == frozenset({"first", "second"})


def test_distance_schedule_reveal_follows_recorded_point_sequence() -> None:
    page = replace(
        _page(),
        strokes=(
            replace(
                _page().strokes[0],
                points=(
                    NormalizedPoint(0, 0),
                    NormalizedPoint(10, 0),
                    NormalizedPoint(10, 30),
                ),
            ),
        ),
        replay_order=("first",),
    )

    frames = progressive_distance_schedule(page, fps=4, drawing_speed=20)

    assert [
        frame.visibility.active_progress
        for frame in frames
        if frame.visibility.active_stroke_id == "first"
    ] == [0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875]


def test_constant_duration_schedule_uses_same_duration_for_each_stroke() -> None:
    frames = progressive_stroke_schedule(_page(), fps=4, seconds_per_stroke=0.5)

    active = [frame.visibility for frame in frames if frame.visibility.active_stroke_id]
    assert [state.active_progress for state in active] == [0.5, 0.5]
    assert frames[-1].visibility.completed_stroke_ids == frozenset({"first", "second"})


def test_progressive_pacing_adds_initial_interstroke_and_final_holds() -> None:
    frames = progressive_stroke_schedule(
        _page(),
        fps=2,
        seconds_per_stroke=0.5,
        initial_pause_seconds=1,
        pause_between_strokes_seconds=0.5,
        final_hold_seconds=1,
    )

    assert [frame.visibility for frame in frames] == [
        frames[0].visibility,
        frames[0].visibility,
        replace(frames[0].visibility, completed_stroke_ids=frozenset({"first"})),
        replace(frames[0].visibility, completed_stroke_ids=frozenset({"first"})),
        replace(
            frames[0].visibility,
            completed_stroke_ids=frozenset({"first", "second"}),
        ),
        replace(
            frames[0].visibility,
            completed_stroke_ids=frozenset({"first", "second"}),
        ),
        replace(
            frames[0].visibility,
            completed_stroke_ids=frozenset({"first", "second"}),
        ),
    ]
    assert [frame.index for frame in frames] == list(range(7))
    assert [frame.time_seconds for frame in frames] == [index / 2 for index in range(7)]


def test_distance_pacing_holds_do_not_change_layer_major_order() -> None:
    frames = progressive_distance_schedule(
        _interleaved_layers_page(),
        fps=2,
        drawing_speed=20,
        pause_between_strokes_seconds=0.5,
    )

    transitions = [
        tuple(sorted(frame.visibility.completed_stroke_ids))
        for frame in frames
        if frame.visibility.active_stroke_id is None
    ]
    assert transitions == [
        ("lower-late",),
        ("lower-late",),
        ("lower-early", "lower-late"),
        ("lower-early", "lower-late"),
        ("lower-early", "lower-late", "upper-early"),
        ("lower-early", "lower-late", "upper-early"),
        ("lower-early", "lower-late", "upper-early", "upper-late"),
    ]


def test_progressive_pacing_rejects_negative_holds() -> None:
    for option in (
        {"initial_pause_seconds": -0.1},
        {"pause_between_strokes_seconds": -0.1},
        {"final_hold_seconds": -0.1},
    ):
        try:
            progressive_stroke_schedule(_page(), fps=2, seconds_per_stroke=1, **option)
        except ValueError as error:
            assert "pause and hold durations must be finite and nonnegative" in str(error)
        else:
            raise AssertionError("negative pacing duration was accepted")


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


def test_duration_schedule_can_complete_multiple_strokes_per_frame():
    from rm_redraw.replay.schedule import duration_schedule

    page = _interleaved_layers_page()
    frames = duration_schedule(page, fps=2, duration_seconds=1, final_hold_seconds=1)
    assert len(frames) == 4
    assert frames[0].visibility.completed_stroke_ids == frozenset({"lower-late", "lower-early"})
    assert frames[1].visibility.completed_stroke_ids == frozenset(page.replay_order)
    assert frames[-1].visibility == frames[1].visibility


def test_duration_schedule_preserves_partial_directional_reveal():
    from rm_redraw.replay.schedule import duration_schedule

    frames = duration_schedule(_page(), fps=4, duration_seconds=1)
    assert frames[0].visibility.active_stroke_id == "first"
    assert frames[0].visibility.active_progress == 0.5
    assert frames[2].visibility.active_stroke_id == "second"
    assert frames[2].visibility.active_progress == 0.5
