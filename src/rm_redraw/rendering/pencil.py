"""Experimental current-pencil profile fitted to app-exported PNG controls.

Fine paper-coordinate grain, coarse occupancy and a separate rough edge
remain fixed during reveal. Sparse pinholes survive full pressure. This is a
statistical approximation, not a copy
of the proprietary texture. Current pencil and mechanical pencil share it.
"""

from math import ceil, floor

import numpy as np


def pressure_coverage(pressure: float) -> float:
    """Base paper occupancy; high pressure retains sparse white pinholes."""
    return float(
        np.interp(
            pressure,
            (
                0,
                16 / 255,
                32 / 255,
                64 / 255,
                96 / 255,
                128 / 255,
                160 / 255,
                192 / 255,
                224 / 255,
                1,
            ),
            (0, 0.0173, 0.0302, 0.1222, 0.2441, 0.4060, 0.5693, 0.7619, 0.8822, 0.970),
        )
    )


def _field(x: np.ndarray, y: np.ndarray, frequency: float, seed: int) -> np.ndarray:
    hx = np.floor(x * frequency).astype(np.uint64)
    hy = np.floor(y * frequency).astype(np.uint64)
    noise = (hx * 374761393 + hy * 668265263 + seed) & 0xFFFFFFFF
    noise = ((noise ^ (noise >> 13)) * 1274126177) & 0xFFFFFFFF
    return (noise & 65535) / 65535.0


def coverage_threshold(x: np.ndarray, y: np.ndarray, pressure: float) -> np.ndarray:
    """Monotone four-source-unit occupancy modulation over one-unit grains.

    The weak coarse field groups grains without making whole strokes darker.
    Pressure knots were refitted on the same 27 horizontal app-PNG controls;
    two/four/eight-pixel patch statistics constrain the modulation. A fixed
    paper field changes deposition odds, not ink opacity or recorded width.
    At maximum pressure the threshold is uniformly .97, preserving pinholes.
    """
    occupancy = pressure_coverage(pressure) / 0.97
    gain = np.exp(0.5 * (2 * _field(x, y, 0.25, 917) - 1))
    return 0.97 * occupancy * gain / (1 - occupancy + occupancy * gain)


def dab(
    alpha: np.ndarray,
    x: float,
    y: float,
    radius: float,
    pressure: float,
    scale_x: float,
    scale_y: float,
    opacity: int,
) -> None:
    """Max-union a reached dab into a supersampled alpha plane.

    Radius is the existing PDF-profile radius (raw quarter width/2 * .70).
    Explicit source alpha is applied once. Paper fields do not depend on stroke
    identity, pressure or sample order, so repeated dabs cannot fill pinholes.
    """
    radius *= 0.77 / 0.70
    amplitude = min(0.9, radius * 0.35)
    extent = radius + amplitude
    left = max(0, floor((x - extent) * scale_x - 1))
    right = min(alpha.shape[1], ceil((x + extent) * scale_x + 1))
    top = max(0, floor((y - extent) * scale_y - 1))
    bottom = min(alpha.shape[0], ceil((y + extent) * scale_y + 1))
    if right <= left or bottom <= top:
        return
    yy, xx = np.mgrid[top:bottom, left:right]
    sx, sy = (xx + 0.5) / scale_x, (yy + 0.5) / scale_y
    distance = np.hypot(sx - x, sy - y)
    boundary = amplitude * (2 * _field(sx, sy, 1.0, 193) - 1)
    edge = np.clip((radius - distance + boundary) * min(scale_x, scale_y) + 0.5, 0, 1)
    grain = _field(sx, sy, 1.0, 0)
    coverage = np.rint(edge * (grain < coverage_threshold(sx, sy, pressure)) * opacity).astype(
        np.uint8
    )
    region = alpha[top:bottom, left:right]
    np.maximum(region, coverage, out=region)
