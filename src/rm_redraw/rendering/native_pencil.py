"""Explicit, checked ctypes adapter for the optional resident Rust pencil kernel."""

import ctypes
import os
from functools import lru_cache
from hashlib import sha256
from pathlib import Path

import numpy as np

from .pencil import pressure_coverage


def library_path() -> Path:
    """Resolve only the explicit override or this checkout's release artifact."""
    override = os.environ.get("RM_REDRAW_PENCIL_LIBRARY")
    return (
        Path(override).expanduser().resolve()
        if override
        else (
            Path(__file__).resolve().parents[3]
            / "artifacts/rust-kernel-build/release/rm_pencil_kernel.dll"
        )
    )


@lru_cache(maxsize=4)
def _library(path: str):
    try:
        library = ctypes.CDLL(path)
        library.rm_pencil_kernel_version.argtypes = []
        library.rm_pencil_kernel_version.restype = ctypes.c_uint32
        if library.rm_pencil_kernel_version() != 1:
            raise RuntimeError("Rust pencil library ABI version must be 1")
        library.rm_pencil_draw.argtypes = [
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
            ctypes.c_size_t,
            ctypes.c_int64,
            ctypes.c_int64,
            ctypes.c_double,
            ctypes.c_double,
            ctypes.c_uint8,
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_size_t,
        ]
        library.rm_pencil_draw.restype = ctypes.c_int32
        return library
    except (OSError, AttributeError) as exc:
        raise RuntimeError(f"Rust pencil library unavailable or incompatible: {path}") from exc


def native_info() -> dict[str, object]:
    """Load and validate the requested binary before emitting output."""
    path = library_path()
    library = _library(str(path))
    return {
        "path": str(path),
        "sha256": sha256(path.read_bytes()).hexdigest(),
        "abi_version": int(library.rm_pencil_kernel_version()),
    }


@lru_cache(maxsize=1)
def _pressure_knots() -> tuple[np.ndarray, np.ndarray]:
    knots = np.array([0, 16, 32, 64, 96, 128, 160, 192, 224, 255], dtype=np.float64) / 255
    values = np.array([pressure_coverage(p) for p in knots], dtype=np.float64)
    knots.flags.writeable = values.flags.writeable = False
    return knots, values


@lru_cache(maxsize=1)
def _gain_table() -> np.ndarray:
    field = np.arange(65536, dtype=np.float64) / 65535.0
    gain = np.exp(0.5 * (2 * field - 1))
    gain.flags.writeable = False
    return gain


def draw_batch(
    alpha: np.ndarray,
    samples,
    scale_x: float,
    scale_y: float,
    opacity: int,
    *,
    origin_x: int = 0,
    origin_y: int = 0,
) -> None:
    """Deposit reached [x,y,radius,pressure] samples into a local uint8 mask.

    Host interpolation and exponential table use the exact NumPy reference
    arithmetic. No fallback is allowed when the Rust backend is requested.
    """
    if not isinstance(alpha, np.ndarray) or alpha.dtype != np.uint8 or alpha.ndim != 2:
        raise ValueError("alpha must be a two-dimensional uint8 array")
    if not alpha.flags.c_contiguous or not alpha.flags.writeable:
        raise ValueError("alpha must be writable and C-contiguous")
    if min(alpha.shape) < 1:
        raise ValueError("alpha dimensions must be positive")
    if not all(np.isfinite(v) and v > 0 for v in (scale_x, scale_y)):
        raise ValueError("scales must be finite and positive")
    if not isinstance(opacity, int) or not 0 <= opacity <= 255:
        raise ValueError("opacity must be an integer in 0..255")
    if any(not isinstance(v, int) or not -(2**63) <= v < 2**63 for v in (origin_x, origin_y)):
        raise ValueError("origins must be signed 64-bit integers")
    data = np.asarray(samples, dtype=np.float64)
    if data.shape == (0,):
        data = np.empty((0, 4), dtype=np.float64)
    if data.ndim != 2 or data.shape[1] != 4:
        raise ValueError("samples must have shape (N, 4)")
    if not np.isfinite(data).all() or (data[:, 2] <= 0).any():
        raise ValueError("samples must be finite with positive radius")
    data = np.array(data, dtype=np.float64, order="C", copy=True)
    # Derive the interpolation knots through the reference function to avoid
    # maintaining a second set of calibration constants.
    knots, values = _pressure_knots()
    data[:, 3] = np.interp(data[:, 3], knots, values) / 0.97
    library = _library(str(library_path()))
    gain = _gain_table()
    status = library.rm_pencil_draw(
        alpha.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
        alpha.shape[1],
        alpha.shape[0],
        origin_x,
        origin_y,
        scale_x,
        scale_y,
        opacity,
        data.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        len(data),
        gain.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        len(gain),
    )
    if status:
        raise RuntimeError(f"Rust pencil kernel rejected the batch (status {status})")
