"""Stable textured deposition with provisional capture-calibrated current tools.

Firmware 3.28.0.172 capture: current pencil/mechanical grid output agrees;
pressure changes deposition density, recorded width controls geometry, and
brush speed changes width. Profiles fit controlled rows, not native grain IDs.
Legacy tool profiles remain experimental and unchanged.

Raw rmscene channels: width is quarter units, pressure 0..255 and direction
is one turn per 255 units. Stable stroke/source-position seeds and fixed
source-distance samples prevent progressive grain resampling.
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
    current = stroke.tool_code in {12, 13, 14} or stroke.tool_name in {
        "PAINTBRUSH_2",
        "MECHANICAL_PENCIL_2",
        "PENCIL_2",
    }
    if current and len({(p.x, p.y) for p in stroke.points}) < 2:
        return
    brush = stroke.tool_code in {0, 12} or (stroke.tool_name or "").startswith("PAINTBRUSH")
    mechanical = stroke.tool_code in {7, 13} or (stroke.tool_name or "").startswith("MECHANICAL")
    seed = int.from_bytes(sha256(stroke.stroke_id.encode()).digest()[:4], "little")
    # Integrate binary source-space grains over pixels instead of replacing
    # grain contrast with a smooth gray fill. Full-canvas phase is frame-stable.
    supersample = 2 if current and not brush else 1
    scale_x *= supersample
    scale_y *= supersample
    alpha = np.zeros((layer.height * supersample, layer.width * supersample), dtype=np.uint8)
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
            if current:
                # Width sweep (raw4/24/96) and high-pressure controls. These
                # are raster profile factors, not claims about native formulas.
                radius *= 0.75 if brush else 0.70
            if brush and not current:
                radius *= 0.35 + 0.65 * pressure
            a0 = left.direction or 0.0
            a1 = right.direction if right.direction is not None else a0
            angle = ((a0 + ((a1 - a0 + 127.5) % 255 - 127.5) * fraction) % 255) * 2 * pi / 255
            if current and brush:
                speed0, speed1 = left.speed or 0.0, right.speed or 0.0
                speed = max(0.0, speed0 + (speed1 - speed0) * fraction)
                # Bounded fit to pressure16/128/255 and speed0/64/240 controls.
                radius *= min(1.0, max(0.0, 2.0 * pressure - 0.107))
                radius *= max(0.0, 1.0 - speed / 300.0)
                radius *= 0.95 - 0.05 * cos(2 * angle)
                if radius < 0.3:
                    next_sample += 0.5
                    continue
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
                current,
            )
            next_sample += 0.5
        traversed += length
        if traversed > visible_length:
            break
    overlay = Image.new("RGBA", layer.size, stroke.rgba[:3] + (0,))
    mask = Image.fromarray(alpha)
    if supersample > 1:
        mask = mask.resize(layer.size, Image.Resampling.BOX)
    overlay.putalpha(mask)
    layer.alpha_composite(overlay)


def _dab(
    alpha: np.ndarray,
    x: float,
    y: float,
    radius: float,
    pressure: float,
    angle: float,
    brush: bool,
    mechanical: bool,
    seed: int,
    scale_x: float,
    scale_y: float,
    opacity: int,
    current: bool = False,
) -> None:
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
    aspect = 0.45 if brush and not current else 1.0
    distance = np.sqrt((along / radius) ** 2 + (across / (radius * aspect)) ** 2)
    edge = np.clip((1 - distance) * radius * min(scale_x, scale_y) + 0.5, 0, 1)
    # Integer hash: stable across processes, frames, crops and Python hash seeds.
    frequency = 0.75 if current and not brush else 1.5
    hx = np.floor(sx * frequency).astype(np.uint64)
    hy = np.floor(sy * frequency).astype(np.uint64)
    noise = (hx * 374761393 + hy * 668265263 + seed) & 0xFFFFFFFF
    noise = ((noise ^ (noise >> 13)) * 1274126177) & 0xFFFFFFFF
    grain = (noise & 65535) / 65535.0
    if current:
        if brush:
            texture, density = 1.0, 1.0
        else:
            texture = (grain < pressure**1.1).astype(float)
            density = 1.0
    elif brush:
        texture = 0.65 + 0.35 * grain
        density = 0.2 + 0.8 * pressure
    else:
        texture = np.clip((grain - (0.55 - 0.45 * pressure)) * 2, 0, 1)
        density = (0.3 + 0.7 * pressure) if mechanical else (0.15 + 0.85 * pressure)
    coverage = np.rint(edge * texture * density * opacity).astype(np.uint8)
    region = alpha[top:bottom, left:right]
    np.maximum(region, coverage, out=region)
