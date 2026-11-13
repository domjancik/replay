from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError, PdfStreamError
from pypdf.generic import ContentStream
from scipy.ndimage import distance_transform_edt
from skimage.feature import canny
from skimage.metrics import structural_similarity

_INK_THRESHOLD = 245
_ROI_PADDING = 12
_HIGH_GAIN = 4


class ComparisonError(ValueError):
    """A local comparison input cannot be compared without changing it."""


@dataclass(frozen=True)
class ComparisonResult:
    output_directory: Path


def run_comparison(
    candidate_png: Path,
    *,
    output_directory: Path,
    native_png: Path | None = None,
    native_pdf: Path | None = None,
    page: int = 1,
    ink_only: bool = False,
) -> ComparisonResult:
    """Compare two same-mode, same-dimension rasters and write a new report directory."""
    if (native_png is None) == (native_pdf is None):
        raise ComparisonError("provide exactly one of native_png or native_pdf")
    if output_directory.exists():
        raise ComparisonError(f"output must be a new output directory: {output_directory}")
    candidate_png = _require_file(candidate_png, "candidate PNG")
    if native_png is not None:
        if ink_only:
            raise ComparisonError("ink-only comparison requires a native PDF")
        native_source = _require_file(native_png, "native PNG")
        native, rasterization = _load_png(native_source, "native PNG"), {"source": "native-png"}
        content_filter = None
    else:
        assert native_pdf is not None
        native_source = _require_file(native_pdf, "native PDF")
        candidate = _load_png(candidate_png, "candidate PNG")
        if ink_only:
            native, rasterization, content_filter = _rasterize_pdf_ink_only(
                native_source, page, candidate.size
            )
        else:
            native, rasterization = _rasterize_pdf(native_source, page, candidate.size)
            content_filter = None

    candidate = _load_png(candidate_png, "candidate PNG")
    _validate_images(candidate, native)

    output_directory.mkdir(parents=True)
    native.save(output_directory / "native.png")
    candidate.save(output_directory / "ours.png")
    native_array = np.asarray(native)
    candidate_array = np.asarray(candidate)
    absolute = np.abs(native_array.astype(np.int16) - candidate_array.astype(np.int16)).astype(
        np.uint8
    )
    Image.fromarray(absolute, mode=candidate.mode).save(output_directory / "absolute-diff.png")
    high_gain = np.clip(absolute.astype(np.uint16) * _HIGH_GAIN, 0, 255).astype(np.uint8)
    Image.fromarray(high_gain, mode=candidate.mode).save(output_directory / "high-gain-diff.png")
    _overlay(native_array, candidate_array).save(output_directory / "overlay.png")

    metrics = _report(
        candidate_png,
        native_source,
        candidate,
        native,
        rasterization,
        content_filter,
        output_directory,
    )
    (output_directory / "metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    return ComparisonResult(output_directory=output_directory)


def _require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise ComparisonError(f"{label} does not exist or is not a file: {path}")
    return path


def _load_png(path: Path, label: str) -> Image.Image:
    try:
        with Image.open(path) as image:
            if image.format != "PNG":
                raise ComparisonError(f"{label} must be a PNG: {path}")
            if image.mode not in {"RGB", "RGBA"}:
                raise ComparisonError(
                    f"{label} must use RGB or RGBA without implicit conversion; found {image.mode}"
                )
            return image.copy()
    except OSError as error:
        raise ComparisonError(f"cannot read {label}: {path}") from error


def _rasterize_pdf(
    pdf: Path, page: int, size: tuple[int, int]
) -> tuple[Image.Image, dict[str, object]]:
    if page < 1:
        raise ComparisonError("PDF page must be at least 1")
    executable = shutil.which("pdftoppm")
    if executable is None:
        raise ComparisonError("Poppler pdftoppm is required to rasterize native PDFs")
    version = subprocess.run([executable, "-v"], capture_output=True, text=True, check=False)
    with tempfile.TemporaryDirectory(prefix="rm-redraw-comparison-") as temporary:
        prefix = Path(temporary) / "native"
        command = [
            executable,
            "-png",
            "-f",
            str(page),
            "-l",
            str(page),
            "-scale-to-x",
            str(size[0]),
            "-scale-to-y",
            str(size[1]),
            "-singlefile",
            str(pdf),
            str(prefix),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        raster = prefix.with_suffix(".png")
        if result.returncode != 0 or not raster.is_file():
            detail = result.stderr.strip() or result.stdout.strip() or "no PNG written"
            raise ComparisonError(f"Poppler failed to rasterize page {page}: {detail}")
        image = _load_png(raster, "Poppler native raster")
    settings: dict[str, object] = {
        "source": "native-pdf",
        "pdf_page": page,
        "rasterizer": "pdftoppm",
        "version": (version.stderr or version.stdout).strip(),
        "settings": {
            "format": "png",
            "scale_to_x": size[0],
            "scale_to_y": size[1],
            "singlefile": True,
        },
    }
    return image, settings


def _rasterize_pdf_ink_only(
    pdf: Path, page: int, size: tuple[int, int]
) -> tuple[Image.Image, dict[str, object], dict[str, object]]:
    """Remove direct PDF text objects, then rasterize the remaining native vector content."""
    with tempfile.TemporaryDirectory(prefix="rm-redraw-comparison-") as temporary:
        filtered_pdf = Path(temporary) / "native-ink-only.pdf"
        removed, text_painting = _write_text_filtered_pdf(pdf, page, filtered_pdf)
        image, rasterization = _rasterize_pdf(filtered_pdf, 1, size)
    rasterization["filtered_pdf_page"] = 1
    rasterization["pdf_page"] = page
    rasterization["content_filter"] = "remove-text-objects-before-rasterization"
    return (
        image,
        rasterization,
        {
            "strategy": "remove-text-objects-from-native-pdf-content-stream",
            "scope": "direct-page-content-only",
            "removed_text_operators": removed,
            "direct_text_painting_operators": text_painting,
            "unfiltered_content": ["form-xobjects", "images", "annotations"],
        },
    )


def _write_text_filtered_pdf(source: Path, page_number: int, destination: Path) -> tuple[int, int]:
    if page_number < 1:
        raise ComparisonError("PDF page must be at least 1")
    try:
        reader = PdfReader(source)
        page = reader.pages[page_number - 1]
        contents = ContentStream(page.get_contents(), reader)
    except (IndexError, OSError, PdfReadError, PdfStreamError) as error:
        raise ComparisonError(f"cannot read PDF page {page_number}: {source}") from error

    filtered_operations: list[tuple[object, object]] = []
    text_depth = 0
    removed = 0
    text_painting = 0
    for operands, operator in contents.operations:
        if operator == b"BT":
            text_depth += 1
        if text_depth:
            removed += 1
            if operator in {b"Tj", b"TJ", b"'", b'"'}:
                text_painting += 1
        else:
            filtered_operations.append((operands, operator))
        if operator == b"ET" and text_depth:
            text_depth -= 1
    if text_depth:
        raise ComparisonError(f"native PDF page {page_number} has an unterminated text object")

    writer = PdfWriter()
    filtered_page = writer.add_page(page)
    filtered_contents = ContentStream(None, writer)
    filtered_contents.operations = filtered_operations
    filtered_page.replace_contents(filtered_contents)
    with destination.open("wb") as output:
        writer.write(output)
    return removed, text_painting


def _validate_images(candidate: Image.Image, native: Image.Image) -> None:
    if candidate.size != native.size:
        raise ComparisonError(
            "candidate and native dimensions differ: "
            f"{candidate.size} versus {native.size}; resize neither input"
        )
    if candidate.mode != native.mode:
        raise ComparisonError(
            "candidate and native colour modes differ: "
            f"{candidate.mode} versus {native.mode}; convert explicitly before comparison"
        )


def _luminance(array: np.ndarray) -> np.ndarray:
    rgb = array[..., :3].astype(float)
    return rgb @ np.array([0.2126, 0.7152, 0.0722])


def _ink_mask(array: np.ndarray) -> np.ndarray:
    return _luminance(array) < _INK_THRESHOLD


def _roi(
    native_ink: np.ndarray, candidate_ink: np.ndarray
) -> tuple[tuple[int, int, int, int], str]:
    ys, xs = np.where(native_ink | candidate_ink)
    height, width = native_ink.shape
    if len(xs) == 0:
        return (0, 0, width, height), "full-image because neither raster has ink below threshold"
    return (
        max(0, int(xs.min()) - _ROI_PADDING),
        max(0, int(ys.min()) - _ROI_PADDING),
        min(width, int(xs.max()) + _ROI_PADDING + 1),
        min(height, int(ys.max()) + _ROI_PADDING + 1),
    ), "union of native and candidate ink masks, expanded and clipped to image bounds"


def _pixel_metrics(native: np.ndarray, candidate: np.ndarray) -> dict[str, float | None]:
    difference = native.astype(float) - candidate.astype(float)
    mae = float(np.mean(np.abs(difference)))
    rmse = float(np.sqrt(np.mean(np.square(difference))))
    if native.shape[0] < 7 or native.shape[1] < 7:
        ssim = None
    else:
        ssim = float(structural_similarity(native, candidate, channel_axis=2, data_range=255))
    return {"mae": mae, "rmse": rmse, "ssim": ssim}


def _coverage_metrics(
    native_ink: np.ndarray, candidate_ink: np.ndarray, native: np.ndarray, candidate: np.ndarray
) -> dict[str, float]:
    return {
        "native_ink_coverage": float(native_ink.mean()),
        "candidate_ink_coverage": float(candidate_ink.mean()),
        "native_ink_density": float((255 - _luminance(native)).mean() / 255),
        "candidate_ink_density": float((255 - _luminance(candidate)).mean() / 255),
    }


def _edge_metrics(native: np.ndarray, candidate: np.ndarray) -> dict[str, float | None]:
    native_edges = canny(_luminance(native) / 255.0)
    candidate_edges = canny(_luminance(candidate) / 255.0)
    if not native_edges.any() and not candidate_edges.any():
        return {
            "native_to_candidate_mean_px": 0.0,
            "candidate_to_native_mean_px": 0.0,
            "symmetric_mean_distance_px": 0.0,
        }
    if not native_edges.any() or not candidate_edges.any():
        return {
            "native_to_candidate_mean_px": None,
            "candidate_to_native_mean_px": None,
            "symmetric_mean_distance_px": None,
        }
    native_to_candidate = distance_transform_edt(~candidate_edges)[native_edges]
    candidate_to_native = distance_transform_edt(~native_edges)[candidate_edges]
    forward = float(native_to_candidate.mean())
    reverse = float(candidate_to_native.mean())
    return {
        "native_to_candidate_mean_px": forward,
        "candidate_to_native_mean_px": reverse,
        "symmetric_mean_distance_px": (forward + reverse) / 2,
    }


def _overlay(native: np.ndarray, candidate: np.ndarray) -> Image.Image:
    native_ink = _ink_mask(native)
    candidate_ink = _ink_mask(candidate)
    overlay = np.full((*native_ink.shape, 3), 255, dtype=np.uint8)
    overlay[native_ink] = (220, 40, 40)
    overlay[candidate_ink] = (40, 90, 220)
    overlay[native_ink & candidate_ink] = (25, 25, 25)
    return Image.fromarray(overlay, mode="RGB")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _background(array: np.ndarray) -> list[int]:
    corners = np.stack((array[0, 0], array[0, -1], array[-1, 0], array[-1, -1]))
    return np.median(corners, axis=0).astype(int).tolist()


def _report(
    candidate_path: Path,
    native_path: Path,
    candidate: Image.Image,
    native: Image.Image,
    rasterization: dict[str, object],
    content_filter: dict[str, object] | None,
    output: Path,
) -> dict[str, object]:
    candidate_array = np.asarray(candidate)
    native_array = np.asarray(native)
    native_ink = _ink_mask(native_array)
    candidate_ink = _ink_mask(candidate_array)
    left, top, right, bottom = _roi(native_ink, candidate_ink)[0]
    roi_native, roi_candidate = (
        native_array[top:bottom, left:right],
        candidate_array[top:bottom, left:right],
    )
    _, roi_description = _roi(native_ink, candidate_ink)
    output_hashes = {
        name: _sha256(output / name)
        for name in (
            "native.png",
            "ours.png",
            "absolute-diff.png",
            "high-gain-diff.png",
            "overlay.png",
        )
    }
    return {
        "schema_version": 1,
        "comparison_scope": "ink-only-native-pdf" if content_filter else "whole-page-raster",
        "inputs": {
            "candidate": {"path": str(candidate_path), "sha256": _sha256(candidate_path)},
            "native": {"path": str(native_path), "sha256": _sha256(native_path)},
        },
        "rasterization": rasterization,
        **({"native_content_filter": content_filter} if content_filter else {}),
        "images": {
            "dimensions": list(candidate.size),
            "mode": candidate.mode,
            "background": {
                "native_corner_median": _background(native_array),
                "candidate_corner_median": _background(candidate_array),
            },
        },
        "roi": {
            "ink_threshold_luminance": _INK_THRESHOLD,
            "padding_px": _ROI_PADDING,
            "bounds_xyxy": [left, top, right, bottom],
            "construction": roi_description,
        },
        "definitions": {
            "mae": "mean absolute per-channel RGB(A) difference on 0-255 samples",
            "rmse": "root mean square per-channel RGB(A) difference on 0-255 samples",
            "ssim": "scikit-image structural_similarity, channel_axis=2, data_range=255",
            "coverage_ink_density": (
                "ink coverage uses luminance < 245; density is mean luminance darkness "
                "over all pixels"
            ),
            "edge_geometry": (
                "Canny luminance edges with symmetric mean nearest-edge Euclidean distance "
                "in pixels"
            ),
        },
        "metrics": {
            "global": {
                **_pixel_metrics(native_array, candidate_array),
                **_coverage_metrics(native_ink, candidate_ink, native_array, candidate_array),
            },
            "ink_roi": {
                **_pixel_metrics(roi_native, roi_candidate),
                **_coverage_metrics(
                    native_ink[top:bottom, left:right],
                    candidate_ink[top:bottom, left:right],
                    roi_native,
                    roi_candidate,
                ),
            },
            "edge_geometry": _edge_metrics(native_array, candidate_array),
        },
        "outputs": output_hashes,
    }
