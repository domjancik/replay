"""Local, deterministic replay command orchestration.

This module intentionally consumes only local page files and archives.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import zipfile
from dataclasses import asdict, dataclass, replace
from io import BytesIO
from numbers import Real
from pathlib import Path
from typing import Literal

from PIL import __version__ as pillow_version
from pypdf import PdfReader
from pypdf.errors import PdfReadError, PdfStreamError

from rm_redraw.comparison.anchor_fit import derive_paired_text_anchor_layout
from rm_redraw.parsing import (
    CrdtIdentifier,
    GeometryResolutionError,
    TextAnchorLayout,
    parse_page,
    resolve_page_geometry,
)
from rm_redraw.parsing.geometry import AffineTransform
from rm_redraw.pipeline import PALETTE_CALIBRATED_CODES, PALETTE_PROFILE, to_render_page
from rm_redraw.rendering import PillowRenderer, RenderOptions, Viewport
from rm_redraw.rendering.types import VisibilityState

from .output import encode_h264, render_png_sequence, write_png
from .schedule import (
    ReplayFrame,
    duration_schedule,
    progressive_distance_schedule,
    progressive_stroke_schedule,
    stroke_step_schedule,
)

ReplayMode = Literal["stroke-step", "seconds-per-stroke", "distance-per-second", "duration"]


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


@dataclass(frozen=True, slots=True)
class PairedExportEvidence:
    """Locally verifiable native-PDF target-canvas evidence."""

    native_pdf_path: Path
    native_pdf_sha256: str
    page: int
    media_box_points: tuple[float, float]
    canvas: tuple[int, int]


@dataclass(frozen=True, slots=True)
class _TextAnchorLayoutEvidence:
    layout: TextAnchorLayout
    source_path: Path | None


def _load_text_anchor_layout(
    source: str | Path | TextAnchorLayout | None,
) -> _TextAnchorLayoutEvidence | None:
    if source is None:
        return None
    if isinstance(source, TextAnchorLayout):
        return _TextAnchorLayoutEvidence(source, None)

    path = Path(source)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or type(payload.get("schema_version")) is not int
            or payload["schema_version"] != 1
        ):
            raise ValueError("schema_version must be 1")
        raw_offsets = payload.get("offsets")
        if not isinstance(raw_offsets, dict):
            raise ValueError("offsets must be an object")
        offsets: dict[CrdtIdentifier, float] = {}
        for raw_id, offset in raw_offsets.items():
            if not isinstance(raw_id, str):
                raise ValueError("offset keys must use PART1:PART2")
            parts = raw_id.split(":")
            if len(parts) != 2:
                raise ValueError(f"invalid anchor ID {raw_id!r}; expected PART1:PART2")
            try:
                part1, part2 = int(parts[0]), int(parts[1])
            except ValueError as error:
                raise ValueError(
                    f"invalid anchor ID {raw_id!r}; expected integer PART1:PART2"
                ) from error
            if part1 < 0 or part2 < 0 or raw_id != f"{part1}:{part2}":
                raise ValueError(
                    f"invalid anchor ID {raw_id!r}; expected canonical nonnegative PART1:PART2"
                )
            anchor_id = CrdtIdentifier(part1, part2)
            offsets[anchor_id] = offset
        layout = TextAnchorLayout(offsets, payload.get("evidence"))
    except (OSError, TypeError, ValueError) as error:
        raise ReplayCommandError(f"invalid --text-anchor-layout {path}: {error}") from error
    return _TextAnchorLayoutEvidence(layout, path)


def _load_paired_export_evidence(
    *,
    paired_native_pdf: str | Path | None,
    paired_pdf_page: int,
    export_canvas: tuple[int, int] | None,
) -> PairedExportEvidence | None:
    if (paired_native_pdf is None) != (export_canvas is None):
        raise ReplayCommandError(
            "--paired-native-pdf and --export-canvas must be supplied together"
        )
    if paired_native_pdf is None:
        return None
    if paired_pdf_page <= 0:
        raise ReplayCommandError("--paired-pdf-page must be positive")

    pdf_path = Path(paired_native_pdf)
    try:
        pdf_bytes = pdf_path.read_bytes()
        reader = PdfReader(BytesIO(pdf_bytes))
        page = reader.pages[paired_pdf_page - 1]
    except (OSError, IndexError, PdfReadError, PdfStreamError, ValueError) as error:
        raise ReplayCommandError(
            f"cannot validate paired native PDF page {paired_pdf_page}: {error}"
        ) from error
    media_box = page.mediabox
    try:
        media_box_points = (float(media_box.width), float(media_box.height))
    except (TypeError, ValueError) as error:
        raise ReplayCommandError("paired native PDF has an invalid page MediaBox") from error
    try:
        canvas_values = tuple(export_canvas)
    except TypeError as error:
        raise ReplayCommandError("invalid --export-canvas") from error
    if len(canvas_values) != 2 or any(
        isinstance(dimension, bool)
        or not isinstance(dimension, Real)
        or not math.isfinite(float(dimension))
        or not float(dimension).is_integer()
        or dimension <= 0
        for dimension in canvas_values
    ):
        raise ReplayCommandError("invalid --export-canvas: dimensions must be positive integers")
    canvas = (int(canvas_values[0]), int(canvas_values[1]))
    return PairedExportEvidence(
        native_pdf_path=pdf_path,
        native_pdf_sha256=_sha256(pdf_bytes),
        page=paired_pdf_page,
        media_box_points=media_box_points,
        canvas=canvas,
    )


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
            source_bytes,
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
    paired_export: PairedExportEvidence | None,
):
    """Adapt shared geometry errors to CLI option names without duplicating resolution."""
    selected_paper_size = paper_size
    selected_source_affine = source_affine
    paper_size_evidence: str | None = None
    transform_evidence: str | None = None
    if paired_export is not None and paper_size is None:
        source_paper_size = parsed_page.paper_size  # type: ignore[attr-defined]
        if source_paper_size is not None and tuple(source_paper_size) != paired_export.canvas:
            raise ReplayCommandError(
                "SceneInfo.paper_size conflicts with --export-canvas; "
                "supply --paper-size WIDTH HEIGHT to select a page canvas"
            )
        if source_paper_size is None:
            selected_paper_size = paired_export.canvas
            paper_size_evidence = (
                "Paired native PDF export canvas; SceneInfo.paper_size was absent."
            )
    if (
        paired_export is not None
        and source_affine is None
        and parsed_page.source_to_page_transform is None  # type: ignore[attr-defined]
    ):
        selected_source_affine = (1, 0, 0, 1, paired_export.canvas[0] / 2, 0)
        transform_evidence = (
            "Centered source frame inferred from paired native PDF export canvas width."
        )
    try:
        geometry = resolve_page_geometry(
            parsed_page,  # type: ignore[arg-type]
            paper_size=selected_paper_size,
            source_to_page_transform=selected_source_affine,
        )
        return replace(
            geometry,
            paper_size_evidence=paper_size_evidence or geometry.paper_size_evidence,
            source_to_page_transform_evidence=(
                transform_evidence or geometry.source_to_page_transform_evidence
            ),
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
    duration_seconds: float | None = None,
    ordering: str = "layer",
    initial_pause_seconds: float,
    pause_between_strokes_seconds: float,
    final_hold_seconds: float,
) -> tuple[ReplayFrame, ...]:
    if ordering not in ("layer", "entry"):
        raise ReplayCommandError("ordering must be layer or entry")
    if fps <= 0:
        raise ReplayCommandError("--fps must be positive")
    if mode == "duration":
        if duration_seconds is None or not math.isfinite(duration_seconds) or duration_seconds <= 0:
            raise ReplayCommandError("--duration must be finite and positive")
        if pause_between_strokes_seconds:
            raise ReplayCommandError("--pause-between-strokes is unsupported with duration mode")
        frames = duration_schedule(
            page,
            fps=fps,
            duration_seconds=duration_seconds,
            ordering=ordering,
            initial_pause_seconds=initial_pause_seconds,
            final_hold_seconds=final_hold_seconds,
        )
    elif mode == "stroke-step":
        frames = stroke_step_schedule(
            page,  # type: ignore[arg-type]
            fps=fps,
            ordering=ordering,
            initial_pause_seconds=initial_pause_seconds,
            pause_between_strokes_seconds=pause_between_strokes_seconds,
            final_hold_seconds=final_hold_seconds,
        )
    elif mode == "seconds-per-stroke":
        if seconds_per_stroke is None:
            raise ReplayCommandError("--seconds-per-stroke is required for seconds-per-stroke mode")
        if not math.isfinite(seconds_per_stroke) or seconds_per_stroke <= 0:
            raise ReplayCommandError("--seconds-per-stroke must be finite and positive")
        frames = progressive_stroke_schedule(
            page,
            fps=fps,
            seconds_per_stroke=seconds_per_stroke,  # type: ignore[arg-type]
            ordering=ordering,
            initial_pause_seconds=initial_pause_seconds,
            pause_between_strokes_seconds=pause_between_strokes_seconds,
            final_hold_seconds=final_hold_seconds,
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
            ordering=ordering,
            initial_pause_seconds=initial_pause_seconds,
            pause_between_strokes_seconds=pause_between_strokes_seconds,
            final_hold_seconds=final_hold_seconds,
        )
    else:
        raise ReplayCommandError(f"unknown replay mode: {mode}")
    return frames or (ReplayFrame(0, 0.0, VisibilityState()),)


def _encoded_timeline(frames: tuple[ReplayFrame, ...], *, fps: int) -> tuple[ReplayFrame, ...]:
    """Use FFmpeg's constant-rate presentation timestamps in rendered output metadata."""
    return tuple(ReplayFrame(frame.index, frame.index / fps, frame.visibility) for frame in frames)


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
    paired_native_pdf: str | Path | None = None,
    paired_pdf_page: int = 1,
    export_canvas: tuple[int, int] | None = None,
    mode: ReplayMode = "stroke-step",
    fps: int = 30,
    seconds_per_stroke: float | None = None,
    distance_per_second: float | None = None,
    duration_seconds: float | None = None,
    ordering: str = "layer",
    initial_pause_seconds: float = 0.0,
    pause_between_strokes_seconds: float = 0.0,
    final_hold_seconds: float = 0.0,
    viewport: tuple[int, int] | None = None,
    replay_strategy: Literal["crdt-order", "scene-order"] = "crdt-order",
    text_anchor_layout: str | Path | TextAnchorLayout | None = None,
    auto_text_anchors: bool = False,
    pencil_boundary: bool = False,
    pencil_backend: str = "python",
) -> ReplayResult:
    """Parse and replay one local page into a new deterministic output directory."""
    if auto_text_anchors and text_anchor_layout is not None:
        raise ReplayCommandError("--auto-text-anchors conflicts with --text-anchor-layout")
    if auto_text_anchors and (paired_native_pdf is None or export_canvas is None):
        raise ReplayCommandError(
            "--auto-text-anchors requires --paired-native-pdf and --export-canvas"
        )
    native_pencil_info = None
    try:
        RenderOptions(pencil_boundary=pencil_boundary, pencil_backend=pencil_backend)
        if pencil_backend == "rust":
            from rm_redraw.rendering.native_pencil import native_info

            native_pencil_info = native_info()
    except (ValueError, RuntimeError) as error:
        raise ReplayCommandError(str(error)) from error
    source_input = _load_input(Path(source), page_id)
    paired_export = _load_paired_export_evidence(
        paired_native_pdf=paired_native_pdf,
        paired_pdf_page=paired_pdf_page,
        export_canvas=export_canvas,
    )
    anchor_layout_evidence = _load_text_anchor_layout(text_anchor_layout)
    parsed_page = parse_page(
        BytesIO(source_input.page_bytes)
        if source_input.page_bytes is not None
        else source_input.source_path,
        page_id=source_input.page_id,
        replay_strategy=replay_strategy,
        text_anchor_layout=(
            anchor_layout_evidence.layout if anchor_layout_evidence is not None else None
        ),
    )
    geometry = _resolve_geometry_or_error(
        parsed_page,
        paper_size=paper_size,
        source_affine=source_affine,
        paired_export=paired_export,
    )
    automatic_layout_manifest = None
    if auto_text_anchors:
        assert paired_export is not None
        try:
            automatic_layout = derive_paired_text_anchor_layout(
                parsed_page,
                paired_export.native_pdf_path,
                pdf_page=paired_export.page,
                canvas=paired_export.canvas,
                source_to_page_transform=geometry.source_to_page_transform,
            )
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            raise ReplayCommandError(f"cannot derive --auto-text-anchors: {error}") from error
        rejected = [decision for decision in automatic_layout.decisions if not decision.accepted]
        if rejected:
            details = "; ".join(
                f"group {decision.group_id}, anchor {decision.anchor_id}: {decision.reason}"
                for decision in rejected
            )
            raise ReplayCommandError(
                f"--auto-text-anchors rejected {details}; verify the paired PDF/page or "
                "supply an evidence-backed --text-anchor-layout instead"
            )
        if automatic_layout.layout is not None:
            anchor_layout_evidence = _TextAnchorLayoutEvidence(automatic_layout.layout, None)
            parsed_page = parse_page(
                BytesIO(source_input.page_bytes),
                page_id=source_input.page_id,
                replay_strategy=replay_strategy,
                text_anchor_layout=automatic_layout.layout,
            )
        automatic_layout_manifest = {
            "schema_version": 1,
            "path": None,
            "origin": "automatic-paired-native-pdf",
            "evidence": automatic_layout.layout.evidence if automatic_layout.layout else None,
            "offsets": {
                str(anchor_id): offset
                for anchor_id, offset in sorted(automatic_layout.layout.offsets.items())
            }
            if automatic_layout.layout
            else {},
            "decisions": [
                {
                    **asdict(decision),
                    "group_id": str(decision.group_id),
                    "anchor_id": str(decision.anchor_id),
                }
                for decision in automatic_layout.decisions
            ],
            "provenance": {
                "algorithm": "paired-native-raster-template-match-v1",
                "native_pdf_path": str(paired_export.native_pdf_path),
                "native_pdf_sha256": paired_export.native_pdf_sha256,
                "pdf_page": paired_export.page,
                "canvas": list(paired_export.canvas),
                "source_to_page_transform": list(geometry.source_to_page_transform),
                "page_sha256": source_input.page_sha256,
            },
        }
    render_page = to_render_page(
        parsed_page,
        paper_size=geometry.paper_size,
        source_to_page_transform=geometry.source_to_page_transform,
    )
    try:
        resolved_viewport = Viewport(*viewport) if viewport is not None else None
    except (TypeError, ValueError) as error:
        raise ReplayCommandError(f"invalid --viewport: {error}") from error
    options = RenderOptions(
        viewport=resolved_viewport, pencil_boundary=pencil_boundary, pencil_backend=pencil_backend
    )
    for option_name, duration in (
        ("--initial-pause", initial_pause_seconds),
        ("--pause-between-strokes", pause_between_strokes_seconds),
        ("--final-hold", final_hold_seconds),
    ):
        if not math.isfinite(duration) or duration < 0:
            raise ReplayCommandError(f"{option_name} must be finite and nonnegative")
    scheduled_frames = _frames_for_mode(
        render_page,
        mode=mode,
        fps=fps,
        seconds_per_stroke=seconds_per_stroke,
        distance_per_second=distance_per_second,
        duration_seconds=duration_seconds,
        ordering=ordering,
        initial_pause_seconds=initial_pause_seconds,
        pause_between_strokes_seconds=pause_between_strokes_seconds,
        final_hold_seconds=final_hold_seconds,
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
        "paired_export": (
            {
                "native_pdf": {
                    "path": str(paired_export.native_pdf_path),
                    "sha256": paired_export.native_pdf_sha256,
                    "page": paired_export.page,
                    "media_box_points": {
                        "width": paired_export.media_box_points[0],
                        "height": paired_export.media_box_points[1],
                    },
                },
                "canvas": {
                    "width": paired_export.canvas[0],
                    "height": paired_export.canvas[1],
                },
                "canvas_evidence": (
                    "Caller-supplied target canvas; no DPI or device scale inferred."
                ),
            }
            if paired_export is not None
            else None
        ),
        "text_anchor_layout": automatic_layout_manifest
        if auto_text_anchors
        else (
            {
                "schema_version": 1,
                "path": (
                    str(anchor_layout_evidence.source_path)
                    if anchor_layout_evidence.source_path is not None
                    else None
                ),
                "evidence": anchor_layout_evidence.layout.evidence,
                "offsets": {
                    str(anchor_id): offset
                    for anchor_id, offset in sorted(anchor_layout_evidence.layout.offsets.items())
                },
            }
            if anchor_layout_evidence is not None
            else None
        ),
        "replay": {
            "mode": mode,
            "ordering": ordering,
            "fps": fps,
            "seconds_per_stroke": seconds_per_stroke,
            "distance_per_second": distance_per_second,
            "duration_seconds": duration_seconds,
            "initial_pause_seconds": initial_pause_seconds,
            "pause_between_strokes_seconds": pause_between_strokes_seconds,
            "final_hold_seconds": final_hold_seconds,
            "timing_evidence": (
                "Discrete stroke events; no wall-clock timing claimed."
                if mode == "stroke-step"
                else "Synthesized timing; source point wall-clock timestamps are unavailable."
            ),
            "strategy": replay_strategy,
            "strategy_evidence": render_page.replay_evidence,
        },
        "viewport": {"width": viewport_size[0], "height": viewport_size[1]},
        "backend": {
            "name": "PillowRenderer",
            "pillow_version": pillow_version,
            "palette_profile": PALETTE_PROFILE,
            "palette_calibrated_codes": list(PALETTE_CALIBRATED_CODES),
            "simple_profile": "current-simple-geometry-v1",
            "marker_profile": "provisional-marker-envelope-v1",
            "highlighter_blend_scope": "within-layer-darken",
            "texture_profile": (
                "experimental-texture-v5-sparse-boundary"
                if pencil_boundary
                else "experimental-texture-v7-clustered-app-png"
            ),
            "pencil_backend": pencil_backend,
            "pencil_kernel": native_pencil_info,
            "texture_native_calibrated": False,
            "current_texture_downsampling": "compose-at-source-then-box",
            "brush_profile": "experimental-brush-app-png-v2",
            "calligraphy_profile": "provisional-calligraphy-raw-width-v1",
            "calligraphy_antialiasing": "4x-pixel-center-area-coverage",
        },
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
