"""Local, deterministic replay command orchestration.

This module intentionally consumes only local page files and archives.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal

from PIL import __version__ as pillow_version

from rm_redraw.parsing import GeometryResolutionError, parse_page, resolve_page_geometry
from rm_redraw.parsing.geometry import AffineTransform
from rm_redraw.pipeline import to_render_page
from rm_redraw.rendering import PillowRenderer, RenderOptions, Viewport
from rm_redraw.rendering.types import VisibilityState

from .output import encode_h264, render_png_sequence, write_png
from .schedule import (
    ReplayFrame,
    progressive_distance_schedule,
    progressive_stroke_schedule,
    stroke_step_schedule,
)

ReplayMode = Literal["stroke-step", "seconds-per-stroke", "distance-per-second"]


class ReplayCommandError(ValueError):
    """An actionable invalid-input or failed-output condition for the local CLI."""


@dataclass(frozen=True, slots=True)
class LocalReplayInput:
    source_path: Path
    input_sha256: str
    page_id: str
    page_member: str
    page_sha256: str
    page_bytes: bytes | None


@dataclass(frozen=True, slots=True)
class ReplayResult:
    output_directory: Path
    manifest_path: Path


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_input(source_path: Path, page_id: str | None) -> LocalReplayInput:
    try:
        source_bytes = source_path.read_bytes()
    except OSError as error:
        raise ReplayCommandError(f"cannot read local source {source_path}: {error}") from error

    suffix = source_path.suffix.lower()
    if suffix == ".rm":
        resolved_page_id = page_id or source_path.stem
        return LocalReplayInput(
            source_path,
            _sha256(source_bytes),
            resolved_page_id,
            source_path.name,
            _sha256(source_bytes),
            None,
        )
    if suffix != ".rmdoc":
        raise ReplayCommandError("source must be a local .rm page or .rmdoc archive")

    try:
        with zipfile.ZipFile(BytesIO(source_bytes)) as archive:
            members = tuple(
                member
                for member in archive.namelist()
                if not member.endswith("/") and member.endswith(".rm")
            )
            if not members:
                raise ReplayCommandError(".rmdoc archive contains no .rm pages")
            page_members = {Path(member).stem: member for member in members}
            if len(page_members) != len(members):
                raise ReplayCommandError(".rmdoc archive has duplicate .rm page identifiers")
            if page_id is None and len(members) > 1:
                raise ReplayCommandError(
                    ".rmdoc archive contains multiple pages; pass --page-id "
                    "with one page identifier"
                )
            resolved_page_id = page_id or next(iter(page_members))
            try:
                member = page_members[resolved_page_id]
            except KeyError as error:
                choices = ", ".join(sorted(page_members))
                raise ReplayCommandError(
                    f"page ID {resolved_page_id!r} is absent from the archive; "
                    f"available IDs: {choices}"
                ) from error
            page_bytes = archive.read(member)
    except zipfile.BadZipFile as error:
        raise ReplayCommandError(f"invalid .rmdoc archive {source_path}: {error}") from error

    return LocalReplayInput(
        source_path,
        _sha256(source_bytes),
        resolved_page_id,
        member,
        _sha256(page_bytes),
        page_bytes,
    )


def _resolve_geometry_or_error(
    parsed_page: object,
    *,
    paper_size: tuple[int, int] | None,
    source_affine: AffineTransform | None,
):
    """Adapt shared geometry errors to CLI option names without duplicating resolution."""
    try:
        return resolve_page_geometry(
            parsed_page,  # type: ignore[arg-type]
            paper_size=paper_size,
            source_to_page_transform=source_affine,
        )
    except GeometryResolutionError as error:
        detail = str(error)
        options: list[str] = []
        if "paper_size" in detail:
            options.append("--paper-size WIDTH HEIGHT")
        if "source_to_page_transform" in detail:
            options.append("--source-affine A B C D E F")
        raise ReplayCommandError(
            f"page geometry is unresolved: {detail}; supply {' and '.join(options)}"
        ) from error
    except ValueError as error:
        detail = str(error)
        option = "--paper-size" if "paper_size" in detail else "--source-affine"
        raise ReplayCommandError(f"invalid {option}: {detail}") from error


def _frames_for_mode(
    page: object,
    *,
    mode: ReplayMode,
    fps: int,
    seconds_per_stroke: float | None,
    distance_per_second: float | None,
) -> tuple[ReplayFrame, ...]:
    if fps <= 0:
        raise ReplayCommandError("--fps must be positive")
    if mode == "stroke-step":
        frames = stroke_step_schedule(page)  # type: ignore[arg-type]
    elif mode == "seconds-per-stroke":
        if seconds_per_stroke is None:
            raise ReplayCommandError("--seconds-per-stroke is required for seconds-per-stroke mode")
        if not math.isfinite(seconds_per_stroke) or seconds_per_stroke <= 0:
            raise ReplayCommandError("--seconds-per-stroke must be finite and positive")
        frames = progressive_stroke_schedule(
            page,
            fps=fps,
            seconds_per_stroke=seconds_per_stroke,  # type: ignore[arg-type]
        )
    elif mode == "distance-per-second":
        if distance_per_second is None:
            raise ReplayCommandError(
                "--distance-per-second is required for distance-per-second mode"
            )
        if not math.isfinite(distance_per_second) or distance_per_second <= 0:
            raise ReplayCommandError("--distance-per-second must be finite and positive")
        frames = progressive_distance_schedule(
            page,
            fps=fps,
            drawing_speed=distance_per_second,  # type: ignore[arg-type]
        )
    else:
        raise ReplayCommandError(f"unknown replay mode: {mode}")
    return frames or (ReplayFrame(0, 0.0, VisibilityState()),)


def _encoded_timeline(frames: tuple[ReplayFrame, ...], *, fps: int) -> tuple[ReplayFrame, ...]:
    """Use FFmpeg's constant-rate presentation timestamps in rendered output metadata."""
    return tuple(
        ReplayFrame(frame.index, frame.index / fps, frame.visibility)
        for frame in frames
    )


def _write_manifest(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def run_local_replay(
    source: str | Path,
    *,
    output_directory: str | Path,
    page_id: str | None = None,
    paper_size: tuple[int, int] | None = None,
    source_affine: AffineTransform | None = None,
    mode: ReplayMode = "stroke-step",
    fps: int = 30,
    seconds_per_stroke: float | None = None,
    distance_per_second: float | None = None,
    viewport: tuple[int, int] | None = None,
    replay_strategy: Literal["crdt-order", "scene-order"] = "crdt-order",
) -> ReplayResult:
    """Parse and replay one local page into a new deterministic output directory."""
    source_input = _load_input(Path(source), page_id)
    parsed_page = parse_page(
        BytesIO(source_input.page_bytes)
        if source_input.page_bytes is not None
        else source_input.source_path,
        page_id=source_input.page_id,
        replay_strategy=replay_strategy,
    )
    geometry = _resolve_geometry_or_error(
        parsed_page,
        paper_size=paper_size,
        source_affine=source_affine,
    )
    render_page = to_render_page(
        parsed_page,
        paper_size=geometry.paper_size,
        source_to_page_transform=geometry.source_to_page_transform,
    )
    try:
        resolved_viewport = Viewport(*viewport) if viewport is not None else None
    except (TypeError, ValueError) as error:
        raise ReplayCommandError(f"invalid --viewport: {error}") from error
    options = RenderOptions(viewport=resolved_viewport)
    scheduled_frames = _frames_for_mode(
        render_page,
        mode=mode,
        fps=fps,
        seconds_per_stroke=seconds_per_stroke,
        distance_per_second=distance_per_second,
    )
    frames = _encoded_timeline(scheduled_frames, fps=fps)

    output_path = Path(output_directory)
    try:
        output_path.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise ReplayCommandError(f"output must be a new output directory: {output_path}") from error

    renderer = PillowRenderer()
    frame_paths = render_png_sequence(
        renderer, render_page, options, frames, output_path / "frames"
    )
    static_path = write_png(
        renderer.render_static(render_page, options), output_path / "static.png"
    )
    final_frame_matches_static = frame_paths[-1].read_bytes() == static_path.read_bytes()
    frame_entries = [
        {
            "index": frame.index,
            "path": path.relative_to(output_path).as_posix(),
            "sha256": _sha256(path.read_bytes()),
            "time_seconds": frame.time_seconds,
        }
        for frame, path in zip(frames, frame_paths, strict=True)
    ]
    viewport_size = renderer.render(render_page, options, VisibilityState()).size
    manifest_payload: dict[str, object] = {
        "schema_version": 1,
        "input": {
            "path": str(source_input.source_path),
            "sha256": source_input.input_sha256,
            "page_id": source_input.page_id,
            "page_member": source_input.page_member,
            "page_sha256": source_input.page_sha256,
        },
        "geometry": {
            "paper_size": list(geometry.paper_size),
            "paper_size_evidence": geometry.paper_size_evidence,
            "source_to_page_transform": list(geometry.source_to_page_transform),
            "transform_evidence": geometry.source_to_page_transform_evidence,
        },
        "replay": {
            "mode": mode,
            "fps": fps,
            "seconds_per_stroke": seconds_per_stroke,
            "distance_per_second": distance_per_second,
            "strategy": replay_strategy,
            "strategy_evidence": render_page.replay_evidence,
        },
        "viewport": {"width": viewport_size[0], "height": viewport_size[1]},
        "backend": {"name": "PillowRenderer", "pillow_version": pillow_version},
        "frame_count": len(frame_entries),
        "frames": frame_entries,
        "static": {"path": "static.png", "sha256": _sha256(static_path.read_bytes())},
        "final_frame_matches_static": final_frame_matches_static,
        "video": None,
    }
    if final_frame_matches_static:
        try:
            video_path = encode_h264(frame_paths, fps=fps, output_path=output_path / "replay.mp4")
        except (OSError, subprocess.CalledProcessError) as error:
            detail = getattr(error, "stderr", b"")
            if isinstance(detail, bytes):
                detail = detail.decode("utf-8", errors="replace").strip()
            manifest_payload["video"] = {
                "path": "replay.mp4",
                "codec": "h264",
                "error": detail or str(error),
            }
            _write_manifest(output_path / "manifest.json", manifest_payload)
            raise ReplayCommandError(
                f"H.264 encoding failed; inspect {output_path / 'manifest.json'} for FFmpeg details"
            ) from error
        else:
            manifest_payload["video"] = {
                "path": video_path.relative_to(output_path).as_posix(),
                "sha256": _sha256(video_path.read_bytes()),
                "codec": "h264",
            }
    manifest_path = _write_manifest(output_path / "manifest.json", manifest_payload)
    if not final_frame_matches_static:
        raise ReplayCommandError(
            f"final replay frame differs from static.png; inspect failed output at {output_path}"
        )
    return ReplayResult(output_path, manifest_path)
