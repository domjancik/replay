"""Geometry helpers shared without coupling replay to a renderer backend."""

from __future__ import annotations

from math import hypot

from .types import NormalizedPoint, NormalizedStroke


def _interpolate_optional(left: float | None, right: float | None, fraction: float) -> float | None:
    if left is None:
        return right
    if right is None:
        return left
    return left + (right - left) * fraction


def stroke_length(stroke: NormalizedStroke) -> float:
    return sum(
        hypot(right.x - left.x, right.y - left.y)
        for left, right in zip(stroke.points, stroke.points[1:], strict=False)
    )


def prefix_points(stroke: NormalizedStroke, progress: float) -> tuple[NormalizedPoint, ...]:
    """Return a distance-based prefix, interpolating its final point."""
    if not stroke.points or progress <= 0:
        return ()
    if progress >= 1 or len(stroke.points) == 1:
        return stroke.points

    total = stroke_length(stroke)
    if total == 0:
        return (stroke.points[0],)
    target = total * progress
    traversed = 0.0
    result = [stroke.points[0]]
    for left, right in zip(stroke.points, stroke.points[1:], strict=False):
        segment = hypot(right.x - left.x, right.y - left.y)
        if traversed + segment <= target:
            result.append(right)
            traversed += segment
            continue
        fraction = (target - traversed) / segment if segment else 0.0
        result.append(
            NormalizedPoint(
                x=left.x + (right.x - left.x) * fraction,
                y=left.y + (right.y - left.y) * fraction,
                pressure=left.pressure + (right.pressure - left.pressure) * fraction,
                speed=_interpolate_optional(left.speed, right.speed, fraction),
                direction=_interpolate_optional(left.direction, right.direction, fraction),
                width=_interpolate_optional(left.width, right.width, fraction),
                extra=left.extra,
            )
        )
        break
    return tuple(result)
