"""Stable textured deposition with provisional capture-calibrated current tools.

Firmware 3.28.0.172 capture: current pencil/mechanical grid output agrees;
pressure changes deposition density, recorded width controls geometry, and
brush speed changes width. Profiles fit controlled rows, not native grain IDs.
Legacy tool profiles remain experimental and unchanged.

Raw rmscene channels: width is quarter units, pressure 0..255 and direction
is one turn per 255 units. Stable stroke/source-position seeds and fixed
source-distance samples prevent progressive grain resampling. Current pencil
grain is shared across strokes: captured coincident overdraw preserves holes.
"""

from hashlib import sha256
from math import ceil, cos, floor, hypot, pi, sin

import numpy as np
from PIL import Image

from .brush import brush_coverage
from .native_pencil import draw_batch as native_pencil_batch
from .pencil import dab as pencil_dab
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
    *,
    pencil_boundary: bool = False,
    pencil_backend: str = "python",
) -> None:
    """Deposit only reached samples; never mask a pre-rendered future stroke."""
    if pencil_backend not in {"python", "rust"}:
        raise ValueError("pencil_backend must be python or rust")
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
    app_pencil = current and not brush and not pencil_boundary
    supersample = 4 if app_pencil else (2 if current else 1)
    scale_x *= supersample
    scale_y *= supersample
    points = stroke.points
    # Full-stroke bounds may include unrevealed points, but only reached dabs
    # deposit ink. Integer output-pixel alignment preserves BOX sampling phase.
    max_radius = max(
        max(0.25, (p.width / 4 if p.width is not None else stroke.thickness_scale) / 2)
        for p in points
    )
    extent = max_radius * 2 + 2 + 1 / min(scale_x, scale_y)
    buffer_left = max(0, floor((min(p.x for p in points) - extent) * scale_x / supersample))
    buffer_top = max(0, floor((min(p.y for p in points) - extent) * scale_y / supersample))
    buffer_right = min(
        layer.width, ceil((max(p.x for p in points) + extent) * scale_x / supersample)
    )
    buffer_bottom = min(
        layer.height, ceil((max(p.y for p in points) + extent) * scale_y / supersample)
    )
    if buffer_right <= buffer_left or buffer_bottom <= buffer_top:
        return
    origin_x, origin_y = buffer_left * supersample, buffer_top * supersample
    alpha = np.zeros(
        ((buffer_bottom - buffer_top) * supersample, (buffer_right - buffer_left) * supersample),
        dtype=np.uint8,
    )
    dirty: tuple[int, int, int, int] | None = None
    native_samples: list[tuple[float, float, float, float]] = []
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
            # Conservative output-pixel bounds retain the global sampling phase.
            # Crop before area averaging: processing an untouched full-page mask
            # for every small stroke is unnecessarily expensive at source scale.
            extent = radius * 2 + 2 + 1 / min(scale_x, scale_y)
            bounds = (
                max(0, floor((x - extent) * scale_x / supersample)),
                max(0, floor((y - extent) * scale_y / supersample)),
                min(layer.width, ceil((x + extent) * scale_x / supersample)),
                min(layer.height, ceil((y + extent) * scale_y / supersample)),
            )
            if bounds[2] > bounds[0] and bounds[3] > bounds[1]:
                dirty = (
                    bounds
                    if dirty is None
                    else (
                        min(dirty[0], bounds[0]),
                        min(dirty[1], bounds[1]),
                        max(dirty[2], bounds[2]),
                        max(dirty[3], bounds[3]),
                    )
                )
            if app_pencil and pencil_backend == "rust":
                native_samples.append((x, y, radius, pressure))
            elif app_pencil:
                pencil_dab(
                    alpha,
                    x,
                    y,
                    radius,
                    pressure,
                    scale_x,
                    scale_y,
                    stroke.rgba[3],
                    origin_x=origin_x,
                    origin_y=origin_y,
                )
            else:
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
                    pencil_boundary,
                    origin_x=origin_x,
                    origin_y=origin_y,
                )
            next_sample += 0.5
        traversed += length
        if traversed > visible_length:
            break
    if app_pencil and pencil_backend == "rust":
        native_pencil_batch(
            alpha,
            native_samples,
            scale_x,
            scale_y,
            stroke.rgba[3],
            origin_x=origin_x,
            origin_y=origin_y,
        )
    if dirty is None:
        return
    left, top, right, bottom = dirty
    size = (right - left, bottom - top)
    overlay = Image.new("RGBA", size, stroke.rgba[:3] + (0,))
    mask = Image.fromarray(alpha).crop(
        (
            left * supersample - origin_x,
            top * supersample - origin_y,
            right * supersample - origin_x,
            bottom * supersample - origin_y,
        )
    )
    if supersample > 1:
        mask = mask.resize(size, Image.Resampling.BOX)
    overlay.putalpha(mask)
    layer.alpha_composite(overlay, dest=(left, top))


def _pencil_coverage(pressure: float) -> float:
    """Monotone occupancy fit to fixed-width native pressure controls.

    Firmware 3.28 current pencil/mechanical: raw width24, speed16, direction0.
    These occupancy knots fit integrated ink mass, not native grain identity;
    pressure/width/path-angle interactions require independent validation.
    """
    return float(
        np.interp(
            pressure,
            (0.0, 16 / 255, 64 / 255, 128 / 255, 192 / 255, 1.0),
            (0.0, 0.047, 0.152, 0.450, 0.797, 1.0),
        )
    )


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
    pencil_boundary: bool = False,
    *,
    origin_x: int = 0,
    origin_y: int = 0,
) -> None:
    boundary_amplitude = (
        min(0.75, radius * 0.3) if pencil_boundary and current and not brush else 0.0
    )
    extent = radius + (0.7 if current and brush else boundary_amplitude)
    left = max(origin_x, floor((x - extent) * scale_x - 1))
    right = min(origin_x + alpha.shape[1], ceil((x + extent) * scale_x + 1))
    top = max(origin_y, floor((y - extent) * scale_y - 1))
    bottom = min(origin_y + alpha.shape[0], ceil((y + extent) * scale_y + 1))
    if right <= left or bottom <= top:
        return
    yy, xx = np.mgrid[top:bottom, left:right]
    sx, sy = (xx + 0.5) / scale_x, (yy + 0.5) / scale_y
    dx, dy = sx - x, sy - y
    along = dx * cos(angle) + dy * sin(angle)
    across = -dx * sin(angle) + dy * cos(angle)
    aspect = 0.45 if brush and not current else 1.0
    distance = np.sqrt((along / radius) ** 2 + (across / (radius * aspect)) ** 2)
    boundary = 0.0
    if boundary_amplitude:
        # A separate paper-coordinate field perturbs only the signed boundary.
        # Keep it pressure-independent so increasing occupancy cannot erase ink.
        # This is an empirical outline model, not native grain reconstruction.
        bx = np.floor(sx * 1.25).astype(np.uint64)
        by = np.floor(sy * 1.25).astype(np.uint64)
        noise = (bx * 374761393 + by * 668265263 + 193) & 0xFFFFFFFF
        noise = ((noise ^ (noise >> 13)) * 1274126177) & 0xFFFFFFFF
        field = (noise & 65535) / 65535.0
        boundary = boundary_amplitude * ((field > 0.94).astype(float) - (field < 0.06))
    edge = np.clip(((1 - distance) * radius + boundary) * min(scale_x, scale_y) + 0.5, 0, 1)
    # Integer hash: stable across processes, frames, crops and Python hash seeds.
    frequency = 0.75 if current and not brush else 1.5
    if current and not brush:
        # Native 1/3/9 coincident-pencil controls retain almost constant ink mass.
        # A shared paper field prevents new stroke IDs filling existing holes.
        # Source-over antialias coverage still accumulates; native union before
        # rasterization is not modeled, and this does not establish grain parity.
        seed = 0
    hx = np.floor(sx * frequency).astype(np.uint64)
    hy = np.floor(sy * frequency).astype(np.uint64)
    noise = (hx * 374761393 + hy * 668265263 + seed) & 0xFFFFFFFF
    noise = ((noise ^ (noise >> 13)) * 1274126177) & 0xFFFFFFFF
    grain = (noise & 65535) / 65535.0
    if current:
        if brush:
            edge = brush_coverage(sx, sy, pressure, (1 - distance) * radius, min(scale_x, scale_y))
            texture, density = 1.0, 1.0
        else:
            texture = (grain < _pencil_coverage(pressure)).astype(float)
            density = 1.0
    elif brush:
        texture = 0.65 + 0.35 * grain
        density = 0.2 + 0.8 * pressure
    else:
        texture = np.clip((grain - (0.55 - 0.45 * pressure)) * 2, 0, 1)
        density = (0.3 + 0.7 * pressure) if mechanical else (0.15 + 0.85 * pressure)
    coverage = np.rint(edge * texture * density * opacity).astype(np.uint8)
    region = alpha[top - origin_y : bottom - origin_y, left - origin_x : right - origin_x]
    np.maximum(region, coverage, out=region)
