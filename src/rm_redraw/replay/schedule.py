"""Replay timing synthesis, deliberately independent from rasterization."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, isfinite

from rm_redraw.rendering.geometry import stroke_length
from rm_redraw.rendering.types import NormalizedPage, VisibilityState


@dataclass(frozen=True, slots=True)
class ReplayFrame:
    index: int
    time_seconds: float
    visibility: VisibilityState


def duration_schedule(
    page: NormalizedPage,
    *,
    fps: int,
    duration_seconds: float,
    initial_pause_seconds: float = 0.0,
    final_hold_seconds: float = 0.0,
    ordering: str = "layer",
) -> tuple[ReplayFrame, ...]:
    """Sample an equal-time-per-stroke timeline at a fixed video duration.

    Several short strokes may complete between video frames. Their deposition
    and compositing order remain unchanged in the renderer.
    """
    if fps <= 0 or not isfinite(duration_seconds) or duration_seconds <= 0:
        raise ValueError("fps and duration_seconds must be finite and positive")
    _validate_pacing(initial_pause_seconds, 0, final_hold_seconds)
    order = ordered_stroke_ids(page, ordering)
    frames: list[ReplayFrame] = []
    _append_hold(frames, VisibilityState(), fps=fps, seconds=initial_pause_seconds)
    count = max(1, ceil(fps * duration_seconds))
    for index in range(1, count + 1):
        # Integer division avoids losing an exact stroke boundary to float error.
        completed_count, remainder = divmod(index * len(order), count)
        visibility = VisibilityState(
            frozenset(order[:completed_count]),
            order[completed_count] if remainder else None,
            remainder / count,
        )
        frames.append(ReplayFrame(len(frames), len(frames) / fps, visibility))
    _append_hold(frames, frames[-1].visibility, fps=fps, seconds=final_hold_seconds)
    return tuple(frames)


def _layered_replay_order(page: NormalizedPage) -> tuple[str, ...]:
    """Order visible layers by compositing order, preserving per-layer replay order."""
    group_by_stroke = {stroke.stroke_id: stroke.group_id for stroke in page.strokes}
    visible_group_ids = {group.group_id for group in page.groups if group.visible}
    return tuple(
        stroke_id
        for group_id in page.compositing_order
        for stroke_id in page.replay_order
        if group_id in visible_group_ids and group_by_stroke[stroke_id] == group_id
    )


def ordered_stroke_ids(page: NormalizedPage, ordering: str = "layer") -> tuple[str, ...]:
    """Choose reveal sequence without changing visual layer compositing."""
    if ordering == "layer":
        return _layered_replay_order(page)
    if ordering != "entry":
        raise ValueError("ordering must be layer or entry")
    visible = {group.group_id for group in page.groups if group.visible}
    visible.intersection_update(page.compositing_order)
    eligible = {stroke.stroke_id for stroke in page.strokes if stroke.group_id in visible}
    return tuple(stroke_id for stroke_id in page.replay_order if stroke_id in eligible)


def _validate_pacing(
    initial_pause_seconds: float,
    pause_between_strokes_seconds: float,
    final_hold_seconds: float,
) -> None:
    durations = (
        initial_pause_seconds,
        pause_between_strokes_seconds,
        final_hold_seconds,
    )
    if any(not isfinite(duration) or duration < 0 for duration in durations):
        raise ValueError("pause and hold durations must be finite and nonnegative")


def _append_hold(
    frames: list[ReplayFrame],
    visibility: VisibilityState,
    *,
    fps: int,
    seconds: float,
) -> None:
    for _ in range(ceil(seconds * fps)):
        frames.append(ReplayFrame(len(frames), len(frames) / fps, visibility))


def stroke_step_schedule(
    page: NormalizedPage,
    *,
    fps: int = 1,
    initial_pause_seconds: float = 0.0,
    pause_between_strokes_seconds: float = 0.0,
    final_hold_seconds: float = 0.0,
    ordering: str = "layer",
) -> tuple[ReplayFrame, ...]:
    """Reveal one stroke in each frame, completing lower layers first."""
    if fps <= 0:
        raise ValueError("fps must be positive")
    _validate_pacing(
        initial_pause_seconds,
        pause_between_strokes_seconds,
        final_hold_seconds,
    )
    completed: frozenset[str] = frozenset()
    frames: list[ReplayFrame] = []
    replay_order = ordered_stroke_ids(page, ordering)
    _append_hold(
        frames,
        VisibilityState(completed),
        fps=fps,
        seconds=initial_pause_seconds,
    )
    for stroke_index, stroke_id in enumerate(replay_order):
        completed = completed | {stroke_id}
        frames.append(ReplayFrame(len(frames), len(frames) / fps, VisibilityState(completed)))
        if stroke_index < len(replay_order) - 1:
            _append_hold(
                frames,
                VisibilityState(completed),
                fps=fps,
                seconds=pause_between_strokes_seconds,
            )
    _append_hold(
        frames,
        VisibilityState(completed),
        fps=fps,
        seconds=final_hold_seconds,
    )
    return tuple(frames)


def progressive_distance_schedule(
    page: NormalizedPage,
    *,
    fps: int,
    drawing_speed: float,
    initial_pause_seconds: float = 0.0,
    pause_between_strokes_seconds: float = 0.0,
    final_hold_seconds: float = 0.0,
    ordering: str = "layer",
) -> tuple[ReplayFrame, ...]:
    """Reveal strokes by geometric distance at the requested drawing speed."""
    if fps <= 0 or drawing_speed <= 0:
        raise ValueError("fps and drawing_speed must be positive")
    _validate_pacing(
        initial_pause_seconds,
        pause_between_strokes_seconds,
        final_hold_seconds,
    )
    strokes = {stroke.stroke_id: stroke for stroke in page.strokes}
    completed: frozenset[str] = frozenset()
    frames: list[ReplayFrame] = []
    replay_order = ordered_stroke_ids(page, ordering)
    _append_hold(
        frames,
        VisibilityState(completed),
        fps=fps,
        seconds=initial_pause_seconds,
    )
    for stroke_index, stroke_id in enumerate(replay_order):
        stroke = strokes[stroke_id]
        frame_count = max(1, ceil(stroke_length(stroke) / drawing_speed * fps))
        for frame_number in range(1, frame_count):
            frames.append(
                ReplayFrame(
                    len(frames),
                    len(frames) / fps,
                    VisibilityState(completed, stroke_id, frame_number / frame_count),
                )
            )
        completed = completed | {stroke_id}
        frames.append(ReplayFrame(len(frames), len(frames) / fps, VisibilityState(completed)))
        if stroke_index < len(replay_order) - 1:
            _append_hold(
                frames,
                VisibilityState(completed),
                fps=fps,
                seconds=pause_between_strokes_seconds,
            )
    _append_hold(
        frames,
        VisibilityState(completed),
        fps=fps,
        seconds=final_hold_seconds,
    )
    return tuple(frames)


def progressive_stroke_schedule(
    page: NormalizedPage,
    *,
    fps: int,
    seconds_per_stroke: float,
    initial_pause_seconds: float = 0.0,
    pause_between_strokes_seconds: float = 0.0,
    final_hold_seconds: float = 0.0,
    ordering: str = "layer",
) -> tuple[ReplayFrame, ...]:
    """Reveal each stroke over a fixed duration, regardless of geometry."""
    if fps <= 0 or seconds_per_stroke <= 0:
        raise ValueError("fps and seconds_per_stroke must be positive")
    _validate_pacing(
        initial_pause_seconds,
        pause_between_strokes_seconds,
        final_hold_seconds,
    )
    frame_count = max(1, ceil(fps * seconds_per_stroke))
    completed: frozenset[str] = frozenset()
    frames: list[ReplayFrame] = []
    replay_order = ordered_stroke_ids(page, ordering)
    _append_hold(
        frames,
        VisibilityState(completed),
        fps=fps,
        seconds=initial_pause_seconds,
    )
    for stroke_index, stroke_id in enumerate(replay_order):
        for frame_number in range(1, frame_count):
            frames.append(
                ReplayFrame(
                    len(frames),
                    len(frames) / fps,
                    VisibilityState(completed, stroke_id, frame_number / frame_count),
                )
            )
        completed = completed | {stroke_id}
        frames.append(ReplayFrame(len(frames), len(frames) / fps, VisibilityState(completed)))
        if stroke_index < len(replay_order) - 1:
            _append_hold(
                frames,
                VisibilityState(completed),
                fps=fps,
                seconds=pause_between_strokes_seconds,
            )
    _append_hold(
        frames,
        VisibilityState(completed),
        fps=fps,
        seconds=final_hold_seconds,
    )
    return tuple(frames)
