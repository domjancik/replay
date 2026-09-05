"""Deterministic frame-sequence output and FFmpeg H.264 encoding."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path

from PIL import Image

from rm_redraw.rendering.protocol import Renderer
from rm_redraw.rendering.types import NormalizedPage, RenderOptions

from .schedule import ReplayFrame


def write_png(image: Image.Image, output_path: Path) -> Path:
    """Write a stable, metadata-free PNG image."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG", compress_level=9)
    return output_path


def render_png_sequence(
    renderer: Renderer,
    page: NormalizedPage,
    options: RenderOptions,
    frames: Iterable[ReplayFrame],
    output_directory: Path,
) -> tuple[Path, ...]:
    """Render independent frames from immutable states into a numbered sequence."""
    paths: list[Path] = []
    for frame in frames:
        path = output_directory / f"frame_{frame.index:06d}.png"
        paths.append(write_png(renderer.render(page, options, frame.visibility), path))
    return tuple(paths)


def encode_h264(sequence: Iterable[Path], *, fps: int, output_path: Path) -> Path:
    """Encode contiguous numbered PNG frames to an H.264 MP4 with FFmpeg."""
    paths = tuple(sequence)
    if not paths:
        raise ValueError("at least one PNG frame is required")
    if fps <= 0:
        raise ValueError("fps must be positive")
    expected = tuple(paths[0].parent / f"frame_{index:06d}.png" for index in range(len(paths)))
    if paths != expected:
        raise ValueError("PNG sequence must be contiguous and start at frame_000000.png")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            str(fps),
            "-start_number",
            "0",
            "-i",
            str(paths[0].parent / "frame_%06d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        check=True,
        capture_output=True,
    )
    return output_path
