"""Provisional current-brush coverage fitted to app-exported PNG controls.

Width and speed geometry remain the caller's responsibility. Calibration uses
isolated horizontal pressure controls from renderer-grid page 6; dynamics and
physical tilt pages are held out. This is a deterministic approximation, not
reconstruction of the native brush texture or stylus pose.
"""

import numpy as np


def _field(x: np.ndarray, y: np.ndarray, frequency: float, seed: int) -> np.ndarray:
    hx = np.floor(x * frequency).astype(np.int64).astype(np.uint64)
    hy = np.floor(y * frequency).astype(np.int64).astype(np.uint64)
    noise = (hx * 374761393 + hy * 668265263 + seed) & 0xFFFFFFFF
    noise = ((noise ^ (noise >> 13)) * 1274126177) & 0xFFFFFFFF
    return (noise & 65535) / 65535.0


def brush_coverage(
    source_x: np.ndarray,
    source_y: np.ndarray,
    pressure: float,
    signed_distance: np.ndarray,
    pixel_scale: float,
) -> np.ndarray:
    """Return unit alpha from source positions and inside-positive distance.

    Fixed paper grain keeps holes stable through dabs and progressive frames.
    The 64/255 control has roughly one third the solid model's ink mass; at
    128/255 its interior is filled. A separate sub-unit edge field models the
    app PNG's fuzzy boundary without applying a second width/tilt multiplier.
    The caller applies explicit stroke alpha once and area-averages samples.
    """
    occupancy = float(
        np.interp(pressure, (0, 16 / 255, 64 / 255, 128 / 255, 1), (0, 0, 0.24, 1, 1))
    )
    grain = _field(source_x, source_y, 1.5, 0)
    edge_extent = float(np.interp(pressure, (0, 128 / 255, 192 / 255, 1), (0.7, 0.7, 0.34, 0.34)))
    boundary = edge_extent * _field(source_x, source_y, 1.25, 193)
    edge = np.clip((signed_distance + boundary) * pixel_scale + 0.5, 0, 1)
    return edge * (grain < occupancy)
