"""Deterministic experimental pencil/brush deposition, not native-calibrated.

Raw rmscene v6 channels: width is quarter units, pressure 0..255 and
 direction is one turn per 255 units. Grain is source-position/stroke seeded.
Profiles below are provisional artistic models, not measured device constants.
"""

from hashlib import sha256
from math import ceil, cos, floor, hypot, pi, sin

import numpy as np
from PIL import Image

from .types import NormalizedStroke

TEXTURED_CODES = {0, 1, 7, 12, 13, 14}
TEXTURED_NAMES = {
    "PAINTBRUSH_1",
    "PAINTBRUSH_2",
    "PENCIL_1",
    "PENCIL_2",
    "MECHANICAL_PENCIL_1",
    "MECHANICAL_PENCIL_2",
}


def draw_texture(
    layer: Image.Image,
    stroke: NormalizedStroke,
    visible_length: float,
    scale_x: float,
    scale_y: float,
) -> None:
    """Deposit only reached samples; never mask a pre-rendered future stroke."""
    brush = stroke.tool_code in {0, 12} or (stroke.tool_name or "").startswith("PAINTBRUSH")
    mechanical = stroke.tool_code in {7, 13} or (stroke.tool_name or "").startswith("MECHANICAL")
    seed = int.from_bytes(sha256(stroke.stroke_id.encode()).digest()[:4], "little")
    alpha = np.zeros((layer.height, layer.width), dtype=np.uint8)
    points = stroke.points
    traversed = 0.0
    next_sample = 0.0
    # Fixed source-space spacing makes each prefix an identical deposition history.
    pairs = list(zip(points, points[1:], strict=False)) or [(points[0], points[0])]
    for left, right in pairs:
        length = hypot(right.x - left.x, right.y - left.y)
        end = min(traversed + length, visible_length)
        while next_sample <= end + 1e-9:
            fraction = (next_sample - traversed) / length if length else 0.0
            x = left.x + (right.x - left.x) * fraction
            y = left.y + (right.y - left.y) * fraction
            pressure = max(
                0.0, min(1.0, (left.pressure + (right.pressure - left.pressure) * fraction) / 255)
            )
            w0 = left.width / 4 if left.width is not None else stroke.thickness_scale
            w1 = right.width / 4 if right.width is not None else stroke.thickness_scale
            radius = max(0.25, (w0 + (w1 - w0) * fraction) / 2)
            if brush:
                radius *= 0.35 + 0.65 * pressure
            a0 = left.direction or 0.0
            a1 = right.direction if right.direction is not None else a0
            angle = ((a0 + ((a1 - a0 + 127.5) % 255 - 127.5) * fraction) % 255) * 2 * pi / 255
            _dab(
                alpha,
                x,
                y,
                radius,
                pressure,
                angle,
                brush,
                mechanical,
                seed,
                scale_x,
                scale_y,
                stroke.rgba[3],
            )
            next_sample += 0.5
        traversed += length
        if traversed > visible_length:
            break
    overlay = Image.new("RGBA", layer.size, stroke.rgba[:3] + (0,))
    overlay.putalpha(Image.fromarray(alpha))
    layer.alpha_composite(overlay)


def _dab(alpha, x, y, radius, pressure, angle, brush, mechanical, seed, scale_x, scale_y, opacity):
    left = max(0, floor((x - radius) * scale_x - 1))
    right = min(alpha.shape[1], ceil((x + radius) * scale_x + 1))
    top = max(0, floor((y - radius) * scale_y - 1))
    bottom = min(alpha.shape[0], ceil((y + radius) * scale_y + 1))
    if right <= left or bottom <= top:
        return
    yy, xx = np.mgrid[top:bottom, left:right]
    sx, sy = (xx + 0.5) / scale_x, (yy + 0.5) / scale_y
    dx, dy = sx - x, sy - y
    along = dx * cos(angle) + dy * sin(angle)
    across = -dx * sin(angle) + dy * cos(angle)
    aspect = 0.45 if brush else 1.0
    distance = np.sqrt((along / radius) ** 2 + (across / (radius * aspect)) ** 2)
    edge = np.clip((1 - distance) * radius * min(scale_x, scale_y) + 0.5, 0, 1)
    # Integer hash: stable across processes, frames, crops and Python hash seeds.
    hx = np.floor(sx * 1.5).astype(np.uint64)
    hy = np.floor(sy * 1.5).astype(np.uint64)
    noise = (hx * 374761393 + hy * 668265263 + seed) & 0xFFFFFFFF
    noise = ((noise ^ (noise >> 13)) * 1274126177) & 0xFFFFFFFF
    grain = (noise & 65535) / 65535.0
    if brush:
        texture = 0.65 + 0.35 * grain
        density = 0.2 + 0.8 * pressure
    else:
        texture = np.clip((grain - (0.55 - 0.45 * pressure)) * 2, 0, 1)
        density = (0.3 + 0.7 * pressure) if mechanical else (0.15 + 0.85 * pressure)
    coverage = np.rint(edge * texture * density * opacity).astype(np.uint8)
    region = alpha[top:bottom, left:right]
    np.maximum(region, coverage, out=region)
