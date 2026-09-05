"""Replay timing synthesis, deliberately independent from rasterization."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from rm_redraw.rendering.geometry import stroke_length
from rm_redraw.rendering.types import NormalizedPage, VisibilityState


@dataclass(frozen=True, slots=True)
class ReplayFrame:
    index: int
    time_seconds: float
    visibility: VisibilityState


def stroke_step_schedule(page: NormalizedPage) -> tuple[ReplayFrame, ...]:
    """Reveal one replay-order stroke in each frame."""
    completed: frozenset[str] = frozenset()
    frames: list[ReplayFrame] = []
    for index, stroke_id in enumerate(page.replay_order):
        completed = completed | {stroke_id}
        frames.append(ReplayFrame(index, float(index), VisibilityState(completed)))
    return tuple(frames)


def progressive_distance_schedule(
    page: NormalizedPage, *, fps: int, drawing_speed: float
) -> tuple[ReplayFrame, ...]:
    """Reveal strokes by geometric distance at the requested drawing speed."""
    if fps <= 0 or drawing_speed <= 0:
        raise ValueError("fps and drawing_speed must be positive")
    strokes = {stroke.stroke_id: stroke for stroke in page.strokes}
    completed: frozenset[str] = frozenset()
    frames: list[ReplayFrame] = []
    for stroke_id in page.replay_order:
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
    return tuple(frames)


def progressive_stroke_schedule(
    page: NormalizedPage, *, fps: int, seconds_per_stroke: float
) -> tuple[ReplayFrame, ...]:
    """Reveal each stroke over a fixed duration, regardless of geometry."""
    if fps <= 0 or seconds_per_stroke <= 0:
        raise ValueError("fps and seconds_per_stroke must be positive")
    frame_count = max(1, ceil(fps * seconds_per_stroke))
    completed: frozenset[str] = frozenset()
    frames: list[ReplayFrame] = []
    for stroke_id in page.replay_order:
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
    return tuple(frames)
