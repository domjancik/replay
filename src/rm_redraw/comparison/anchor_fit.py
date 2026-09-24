"""Reference-assisted text-anchor fitting with explicit ambiguity rejection."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, replace
from math import ceil, floor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from pypdf import PdfReader
from scipy.ndimage import distance_transform_edt, map_coordinates

from rm_redraw.comparison.command import _rasterize_pdf_ink_only
from rm_redraw.parsing.model import (
    CrdtIdentifier,
    NormalizedPage,
    TextAnchorLayout,
)


@dataclass(frozen=True, slots=True)
class TranslationCandidate:
    translation_x: float
    translation_y: float
    capped_mean_distance_px: float
    fraction_within_2px: float
    native_fraction_within_5px: float | None = None


@dataclass(frozen=True, slots=True)
class AnchorTemplateFit:
    accepted: bool
    reason: str
    best_candidate: TranslationCandidate
    second_candidate: TranslationCandidate | None

    @property
    def translation_x(self) -> float:
        return self.best_candidate.translation_x

    @property
    def translation_y(self) -> float:
        return self.best_candidate.translation_y

    @property
    def fraction_within_2px(self) -> float:
        return self.best_candidate.fraction_within_2px


@dataclass(frozen=True, slots=True)
class PairedAnchorDecision:
    group_id: CrdtIdentifier
    anchor_id: CrdtIdentifier
    accepted: bool
    reason: str
    offset_from_root_text_y: float | None
    fit: AnchorTemplateFit | None


@dataclass(frozen=True, slots=True)
class PairedAnchorLayout:
    layout: TextAnchorLayout | None
    decisions: tuple[PairedAnchorDecision, ...]


def native_vector_ink_mask(
    native_pdf: str | Path,
    *,
    page: int,
    canvas: tuple[int, int],
) -> np.ndarray:
    """Rasterize visible native ink with direct text removed, in the supplied canvas."""
    if page <= 0:
        raise ValueError("native PDF page must be positive")
    if len(canvas) != 2 or canvas[0] <= 0 or canvas[1] <= 0:
        raise ValueError("native canvas dimensions must be positive")
    try:
        pdf_page = PdfReader(Path(native_pdf)).pages[page - 1]
    except (OSError, IndexError, ValueError) as error:
        raise ValueError(f"cannot read native PDF page {page}: {error}") from error
    operations = pdf_page.get_contents().operations
    if any(operator in {b"Do", b"INLINE IMAGE"} for _operands, operator in operations):
        raise ValueError("native anchor fitting does not support unfiltered XObjects or images")
    if any(op == b"Tr" and args and int(args[0]) >= 4 for args, op in operations):
        raise ValueError("native anchor fitting: text clipping is unsupported")
    annotations = pdf_page.get("/Annots")
    if annotations is not None and annotations.get_object():
        raise ValueError("native anchor fitting: annotations are unsupported")
    source_scale = None
    for operands, operator in operations:
        if operator != b"cm" or len(operands) != 6:
            continue
        a, b, c, d, _e, _f = (float(value) for value in operands)
        if b == 0 and c == 0 and a > 0 and d < 0 and abs(abs(a) - abs(d)) < 1e-6:
            source_scale = 1.0 / a
            break
    if source_scale is None:
        raise ValueError("native PDF has no source-coordinate transform")
    expected = (
        float(pdf_page.mediabox.width) * source_scale,
        float(pdf_page.mediabox.height) * source_scale,
    )
    if any(abs(actual - inferred) > 3 for actual, inferred in zip(canvas, expected, strict=True)):
        raise ValueError(
            f"native PDF source transform implies canvas {expected}, not caller canvas {canvas}"
        )

    # Let the same PDF interpreter used for comparisons handle the graphics-state
    # stack, curves, even-odd holes, clip paths, alpha and overpainting. Reading
    # m/l operands directly silently discards all of those PDF semantics.
    image, _rasterization, _filter = _rasterize_pdf_ink_only(Path(native_pdf), page, canvas)
    mask = np.asarray(image.convert("L")) < 245
    if not mask.any():
        raise ValueError("native PDF page contains no visible vector ink")
    return mask


def _root_text_pos_y(page: NormalizedPage) -> float:
    root_text = next(
        (
            block
            for block in page.diagnostics.blocks
            if block.block_name == "RootTextBlock" and not block.unreadable
        ),
        None,
    )
    try:
        value = root_text.fields["value"]["pos_y"]  # type: ignore[index,union-attr]
        result = float(value)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("parsed page does not retain a usable RootText.pos_y") from error
    if not np.isfinite(result):
        raise ValueError("parsed RootText.pos_y must be finite")
    return result


def _anchor_type(group_extra: dict[str, object]) -> int | None:
    value = group_extra.get("anchor_type")
    if not isinstance(value, dict):
        return None
    raw_type = value.get("value")
    return int(raw_type) if isinstance(raw_type, int) and not isinstance(raw_type, bool) else None


def derive_paired_text_anchor_layout(
    page: NormalizedPage,
    native_pdf: str | Path,
    *,
    pdf_page: int,
    canvas: tuple[int, int],
    source_to_page_transform: tuple[float, float, float, float, float, float],
) -> PairedAnchorLayout:
    """Infer only unique direct-group anchor matches from a paired native export."""
    if not any(
        group.local_transform.anchor_ids and _anchor_type(group.extra) == 2 for group in page.groups
    ):
        return PairedAnchorLayout(None, ())
    a, b, c, d, page_tx, page_ty = source_to_page_transform
    if (a, b, c, d) != (1, 0, 0, 1):
        raise ValueError(
            "paired anchor fitting currently requires a translation-only page transform"
        )
    root_pos_y = _root_text_pos_y(page)
    native_mask = native_vector_ink_mask(native_pdf, page=pdf_page, canvas=canvas)
    decisions: list[PairedAnchorDecision] = []
    groups_by_id = {group.node_id: group for group in page.groups}
    for group in page.groups:
        anchor_ids = group.local_transform.anchor_ids
        if not anchor_ids or _anchor_type(group.extra) != 2:
            continue
        anchor_id = anchor_ids[0]
        parent_id = group.parent_id
        visited = {group.node_id}
        unsupported_ancestor = False
        while parent_id in groups_by_id:
            ancestor = groups_by_id[parent_id]
            if parent_id in visited or not ancestor.effective_transform.resolved:
                unsupported_ancestor = True
                break
            visited.add(parent_id)
            parent_id = ancestor.parent_id
        if unsupported_ancestor:
            decisions.append(
                PairedAnchorDecision(
                    group.node_id,
                    anchor_id,
                    False,
                    "unsupported-unresolved-ancestor",
                    None,
                    None,
                )
            )
            continue
        matrix = group.local_transform.matrix
        effective = group.effective_transform.matrix
        if matrix[:4] != (1, 0, 0, 1) or effective[:4] != (1, 0, 0, 1):
            decisions.append(
                PairedAnchorDecision(
                    group.node_id,
                    anchor_id,
                    False,
                    "unsupported-nontranslation-group-transform",
                    None,
                    None,
                )
            )
            continue
        strokes = tuple(
            np.asarray([(point.x, point.y) for point in stroke.points], dtype=float)
            for stroke in page.strokes
            if stroke.parent_id == group.node_id and len(stroke.points) >= 2
        )
        if not strokes:
            decisions.append(
                PairedAnchorDecision(
                    group.node_id,
                    anchor_id,
                    False,
                    "unsupported-no-direct-stroke-template",
                    None,
                    None,
                )
            )
            continue
        fit = fit_anchor_template(
            native_mask,
            strokes,
            expected_x=page_tx + effective[4],
        )
        if not fit.accepted:
            decisions.append(
                PairedAnchorDecision(
                    group.node_id,
                    anchor_id,
                    False,
                    fit.reason,
                    None,
                    fit,
                )
            )
            continue
        parent_y = effective[5] - matrix[5]
        offset = fit.translation_y - page_ty - parent_y - root_pos_y
        decisions.append(
            PairedAnchorDecision(
                group.node_id,
                anchor_id,
                True,
                fit.reason,
                offset,
                fit,
            )
        )
    # Layouts are keyed by anchor ID rather than group ID. A value would also
    # resolve every other group referencing that ID, including rejected groups.
    # Require unanimous, identical evidence instead of silently overwriting it.
    offsets: dict[CrdtIdentifier, float] = {}
    for anchor_id in {decision.anchor_id for decision in decisions}:
        related = [decision for decision in decisions if decision.anchor_id == anchor_id]
        values = {decision.offset_from_root_text_y for decision in related if decision.accepted}
        reason = None
        if len(values) > 1:
            reason = "conflicting-shared-anchor-offsets"
        elif any(not decision.accepted for decision in related):
            reason = "unresolved-shared-anchor-group"
        if reason is not None:
            decisions = [
                replace(decision, accepted=False, reason=reason, offset_from_root_text_y=None)
                if decision.anchor_id == anchor_id and decision.accepted
                else decision
                for decision in decisions
            ]
        elif values:
            value = next(iter(values))
            assert value is not None
            offsets[anchor_id] = value
    if not offsets:
        return PairedAnchorLayout(None, tuple(decisions))
    evidence = (
        f"Automatic paired-native-PDF raster template match on page {pdf_page}; "
        f"PDF SHA256 {hashlib.sha256(Path(native_pdf).read_bytes()).hexdigest()}; "
        f"Poppler pdftoppm PNG at {canvas[0]}x{canvas[1]}, direct text objects removed, "
        "luminance threshold <245; only unique, "
        "shape-consistent direct-group matches are included and ambiguous groups remain unresolved"
    )
    return PairedAnchorLayout(TextAnchorLayout(offsets, evidence), tuple(decisions))


def _sample_candidate(
    distance: np.ndarray,
    points: np.ndarray,
    translation_x: float,
    translation_y: float,
    cap: float,
) -> TranslationCandidate:
    sampled = map_coordinates(
        distance,
        [points[:, 1] + translation_y, points[:, 0] + translation_x],
        order=1,
        mode="constant",
        cval=cap,
    )
    return TranslationCandidate(
        translation_x=float(translation_x),
        translation_y=float(translation_y),
        capped_mean_distance_px=float(np.minimum(sampled, cap).mean()),
        fraction_within_2px=float(np.mean(sampled <= 2.0)),
    )


def _normalize_strokes(points: np.ndarray | Sequence[np.ndarray]) -> tuple[np.ndarray, ...]:
    if isinstance(points, np.ndarray):
        raw_strokes = (points,)
    else:
        raw_strokes = tuple(points)
    strokes: list[np.ndarray] = []
    for raw_stroke in raw_strokes:
        stroke = np.asarray(raw_stroke, dtype=float)
        if stroke.ndim != 2 or stroke.shape[1:] != (2,) or len(stroke) < 2:
            raise ValueError("each anchor template stroke must contain at least two XY points")
        if not np.isfinite(stroke).all():
            raise ValueError("anchor template coordinates must be finite")
        strokes.append(stroke)
    if not strokes:
        raise ValueError("anchor template must contain at least one stroke")
    return tuple(strokes)


def _densify_stroke(stroke: np.ndarray) -> np.ndarray:
    result = [stroke[0]]
    for left, right in zip(stroke, stroke[1:], strict=False):
        distance = float(np.linalg.norm(right - left))
        steps = max(1, ceil(distance))
        result.extend(left + (right - left) * (step / steps) for step in range(1, steps + 1))
    return np.asarray(result)


def _with_shape_consistency(
    native_mask: np.ndarray,
    strokes: tuple[np.ndarray, ...],
    candidate: TranslationCandidate,
) -> TranslationCandidate:
    translated = tuple(
        stroke + np.asarray((candidate.translation_x, candidate.translation_y))
        for stroke in strokes
    )
    all_points = np.concatenate(translated)
    margin = 6
    left = max(0, floor(float(all_points[:, 0].min())) - margin)
    top = max(0, floor(float(all_points[:, 1].min())) - margin)
    right = min(native_mask.shape[1], ceil(float(all_points[:, 0].max())) + margin + 1)
    bottom = min(native_mask.shape[0], ceil(float(all_points[:, 1].max())) + margin + 1)
    template_image = Image.new("1", (right - left, bottom - top), 0)
    draw = ImageDraw.Draw(template_image)
    for stroke in translated:
        draw.line(
            [(float(x) - left, float(y) - top) for x, y in stroke],
            fill=1,
            width=1,
        )
    template_mask = np.asarray(template_image, dtype=bool)
    native_crop = native_mask[top:bottom, left:right]
    native_pixels = native_crop & np.ones_like(template_mask)
    if not native_pixels.any():
        reverse_fraction = 0.0
    else:
        template_distance = distance_transform_edt(~template_mask)
        reverse_fraction = float(np.mean(template_distance[native_pixels] <= 5.0))
    return TranslationCandidate(
        candidate.translation_x,
        candidate.translation_y,
        candidate.capped_mean_distance_px,
        candidate.fraction_within_2px,
        reverse_fraction,
    )


def _integer_candidates(
    distance: np.ndarray,
    points: np.ndarray,
    expected_x: float,
    *,
    x_tolerance: int,
    cap: float,
) -> list[TranslationCandidate]:
    height, _width = distance.shape
    first_y = ceil(-float(points[:, 1].min()))
    last_y = floor((height - 1) - float(points[:, 1].max()))
    if first_y > last_y:
        raise ValueError("anchor template cannot fit inside the native canvas")
    y_values = np.arange(first_y, last_y + 1, dtype=float)
    candidates: list[TranslationCandidate] = []
    for translation_x in range(
        round(expected_x) - x_tolerance,
        round(expected_x) + x_tolerance + 1,
    ):
        scores = np.empty(len(y_values), dtype=float)
        hits = np.empty(len(y_values), dtype=float)
        for start in range(0, len(y_values), 256):
            batch = y_values[start : start + 256]
            y_coordinates = points[:, 1, None] + batch[None, :]
            x_coordinates = np.broadcast_to(
                points[:, 0, None] + translation_x,
                y_coordinates.shape,
            )
            sampled = map_coordinates(
                distance,
                [y_coordinates.ravel(), x_coordinates.ravel()],
                order=1,
                mode="constant",
                cval=cap,
            ).reshape(y_coordinates.shape)
            scores[start : start + len(batch)] = np.minimum(sampled, cap).mean(axis=0)
            hits[start : start + len(batch)] = np.mean(sampled <= 2.0, axis=0)
        candidates.extend(
            TranslationCandidate(float(translation_x), float(y), float(score), float(hit))
            for y, score, hit in zip(y_values, scores, hits, strict=True)
        )
    return candidates


def _distinct_best(
    candidates: list[TranslationCandidate], *, expected_x: float, y_separation: float
) -> tuple[TranslationCandidate, TranslationCandidate | None]:
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            candidate.capped_mean_distance_px,
            -candidate.fraction_within_2px,
            abs(candidate.translation_x - expected_x),
        ),
    )
    best = ordered[0]
    second = next(
        (
            candidate
            for candidate in ordered[1:]
            if abs(candidate.translation_y - best.translation_y) >= y_separation
        ),
        None,
    )
    return best, second


def _refine_candidate(
    distance: np.ndarray,
    points: np.ndarray,
    candidate: TranslationCandidate,
    expected_x: float,
    cap: float,
) -> TranslationCandidate:
    refined = candidate
    for translation_x in np.arange(
        candidate.translation_x - 1,
        candidate.translation_x + 1.01,
        0.25,
    ):
        for translation_y in np.arange(
            candidate.translation_y - 1,
            candidate.translation_y + 1.01,
            0.25,
        ):
            trial = _sample_candidate(distance, points, translation_x, translation_y, cap)
            if (
                trial.capped_mean_distance_px,
                -trial.fraction_within_2px,
                abs(trial.translation_x - expected_x),
            ) < (
                refined.capped_mean_distance_px,
                -refined.fraction_within_2px,
                abs(refined.translation_x - expected_x),
            ):
                refined = trial
    return refined


def fit_anchor_template(
    native_ink_mask: np.ndarray,
    points: np.ndarray | Sequence[np.ndarray],
    *,
    expected_x: float,
    x_tolerance: int = 4,
    cap: float = 25.0,
    minimum_fraction_within_2px: float = 0.35,
    minimum_native_fraction_within_5px: float = 0.60,
    minimum_relative_score_gap: float = 0.10,
    distinct_y_separation: float = 16.0,
) -> AnchorTemplateFit:
    """Fit one local stroke template, rejecting weak or non-unique native matches."""
    mask = np.asarray(native_ink_mask, dtype=bool)
    strokes = _normalize_strokes(points)
    template = np.concatenate(tuple(_densify_stroke(stroke) for stroke in strokes))
    if mask.ndim != 2 or not mask.any():
        raise ValueError("native ink mask must be a non-empty two-dimensional array")
    if not np.isfinite(expected_x):
        raise ValueError("anchor template coordinates must be finite")
    if x_tolerance < 0 or cap <= 0 or distinct_y_separation <= 0:
        raise ValueError("anchor fit search parameters must be positive")

    distance = distance_transform_edt(~mask)
    candidates = _integer_candidates(
        distance,
        template,
        expected_x,
        x_tolerance=x_tolerance,
        cap=cap,
    )
    best, second = _distinct_best(
        candidates,
        expected_x=expected_x,
        y_separation=distinct_y_separation,
    )
    best = _refine_candidate(distance, template, best, expected_x, cap)
    if second is not None:
        second = _refine_candidate(distance, template, second, expected_x, cap)
    best = _with_shape_consistency(mask, strokes, best)
    if best.fraction_within_2px < minimum_fraction_within_2px:
        return AnchorTemplateFit(False, "insufficient-native-overlap", best, second)
    if (
        best.native_fraction_within_5px is None
        or best.native_fraction_within_5px < minimum_native_fraction_within_5px
    ):
        return AnchorTemplateFit(False, "inconsistent-native-shape", best, second)
    if second is not None:
        denominator = max(second.capped_mean_distance_px, 1e-9)
        relative_gap = (second.capped_mean_distance_px - best.capped_mean_distance_px) / denominator
        if relative_gap < minimum_relative_score_gap:
            return AnchorTemplateFit(False, "ambiguous-native-match", best, second)
    return AnchorTemplateFit(True, "unique-native-match", best, second)
