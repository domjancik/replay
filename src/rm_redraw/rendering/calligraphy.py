"""Antialiased, provisional raw-width envelope for current calligraphy (tool 21).

Firmware 3.28 page 11 even-column controls establish quarter-unit raw widths,
independent of the stored pressure, direction, speed and thickness channels.
Supplement stationary controls are blank; a nonzero short path paints ink.
The smooth swept-circle envelope does not reproduce native polygon simplification
or establish a directional nib model. At raw width 96, native width is about
22.125 rather than the nominal 24, so broad-edge equivalence remains unproven.
"""

from __future__ import annotations

from math import ceil, floor, hypot

import numpy as np
from PIL import Image

from .types import NormalizedPoint, NormalizedStroke

_SUPERSAMPLE = 4


def draw_calligraphy(
    layer: Image.Image,
    points: tuple[NormalizedPoint, ...],
    stroke: NormalizedStroke,
    scale_x: float,
    scale_y: float,
) -> None:
    """Union segment coverage, then composite source RGBA once for this stroke.

    `points` is the visible distance prefix; geometry is evaluated against the
    original segments in `stroke.points`. This avoids rerasterizing a slightly
    different slope as a fractional endpoint advances. The absolute subpixel
    lattice is identical for every frame and respects anisotropic viewports.
    """
    visible_length = sum(
        hypot(b.x - a.x, b.y - a.y) for a, b in zip(points, points[1:], strict=False)
    )
    if visible_length <= 0 or not stroke.points:
        return
    radii = [
        max(0.0, p.width / 8 if p.width is not None else stroke.thickness_scale / 2)
        for p in stroke.points
    ]
    radius = max(radii)
    if radius <= 0:
        return
    left = max(0, floor((min(p.x for p in points) - radius) * scale_x) - 3)
    right = min(layer.width, ceil((max(p.x for p in points) + radius) * scale_x) + 3)
    top = max(0, floor((min(p.y for p in points) - radius) * scale_y) - 3)
    bottom = min(layer.height, ceil((max(p.y for p in points) + radius) * scale_y) + 3)
    if right <= left or bottom <= top:
        return
    ss = _SUPERSAMPLE
    mask = np.zeros(((bottom - top) * ss, (right - left) * ss), dtype=bool)
    remaining = visible_length
    for i, (a, b) in enumerate(zip(stroke.points, stroke.points[1:], strict=False)):
        dx, dy = b.x - a.x, b.y - a.y
        length = hypot(dx, dy)
        if length <= 0:
            continue
        if remaining <= 0:
            break
        fraction = min(1.0, remaining / length)
        remaining -= length
        r0, dr = radii[i], radii[i + 1] - radii[i]
        end_x, end_y = a.x + dx * fraction, a.y + dy * fraction
        max_radius = max(r0, r0 + dr * fraction)
        if max_radius <= 0:
            continue
        x0 = max(left, floor((min(a.x, end_x) - max_radius) * scale_x))
        x1 = min(right, ceil((max(a.x, end_x) + max_radius) * scale_x))
        y0 = max(top, floor((min(a.y, end_y) - max_radius) * scale_y))
        y1 = min(bottom, ceil((max(a.y, end_y) + max_radius) * scale_y))
        if x1 <= x0 or y1 <= y0:
            continue
        x = (np.arange(x0 * ss, x1 * ss, dtype=float) + 0.5) / (ss * scale_x) - a.x
        y = (np.arange(y0 * ss, y1 * ss, dtype=float) + 0.5) / (ss * scale_y) - a.y
        px, py = x[None, :], y[:, None]
        # Minimize squared distance minus squared interpolated radius over the
        # visible parameter interval. A concave quadratic has endpoint minima.
        denominator = dx * dx + dy * dy - dr * dr
        if denominator > 0:
            t = np.clip((px * dx + py * dy + r0 * dr) / denominator, 0, fraction)
            covered = (px - dx * t) ** 2 + (py - dy * t) ** 2 <= (r0 + dr * t) ** 2
        else:
            covered = (px * px + py * py <= r0 * r0) | (
                (px - dx * fraction) ** 2 + (py - dy * fraction) ** 2 <= (r0 + dr * fraction) ** 2
            )
        mask[(y0 - top) * ss : (y1 - top) * ss, (x0 - left) * ss : (x1 - left) * ss] |= covered
    coverage = Image.fromarray(mask.astype(np.uint8) * 255).resize(
        (right - left, bottom - top), Image.Resampling.BOX
    )
    if stroke.rgba[3] != 255:
        coverage = coverage.point(lambda alpha: round(alpha * stroke.rgba[3] / 255))
    ink = Image.new("RGBA", coverage.size, stroke.rgba)
    ink.putalpha(coverage)
    layer.alpha_composite(ink, (left, top))
