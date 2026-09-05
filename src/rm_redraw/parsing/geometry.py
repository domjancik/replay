"""Evidence-carrying resolution of page size and source coordinates."""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .model import NormalizedPage

type AffineTransform = tuple[float, float, float, float, float, float]


class GeometryResolutionError(ValueError):
    """Raised when source metadata and caller values cannot resolve page geometry."""


@dataclass(frozen=True)
class PageGeometry:
    """Resolved page geometry with human-readable provenance for each value."""

    paper_size: tuple[int, int]
    source_to_page_transform: AffineTransform
    paper_size_evidence: str
    source_to_page_transform_evidence: str


def _paper_size(value: object) -> tuple[int, int]:
    try:
        values = tuple(value)  # type: ignore[arg-type]
    except TypeError as error:
        raise ValueError("paper_size must contain two positive integer dimensions") from error
    if len(values) != 2:
        raise ValueError("paper_size must contain two positive integer dimensions")
    if any(
        isinstance(dimension, bool)
        or not isinstance(dimension, Real)
        or not math.isfinite(float(dimension))
        or float(dimension) <= 0
        or not float(dimension).is_integer()
        for dimension in values
    ):
        raise ValueError("paper_size dimensions must be positive finite integers")
    return (int(values[0]), int(values[1]))


def _affine_transform(value: object) -> AffineTransform:
    try:
        values = tuple(value)  # type: ignore[arg-type]
    except TypeError as error:
        raise ValueError(
            "source_to_page_transform must contain six finite numbers"
        ) from error
    if len(values) != 6 or any(
        isinstance(component, bool)
        or not isinstance(component, Real)
        or not math.isfinite(float(component))
        for component in values
    ):
        raise ValueError("source_to_page_transform must contain six finite numbers")
    return tuple(float(component) for component in values)  # type: ignore[return-value]


def resolve_page_geometry(
    page: NormalizedPage,
    *,
    paper_size: Sequence[Real] | None = None,
    source_to_page_transform: Sequence[Real] | None = None,
) -> PageGeometry:
    """Resolve geometry from explicit caller overrides, then parsed source values."""

    source_paper_size = page.paper_size
    source_transform = page.source_to_page_transform
    missing: list[str] = []
    if source_paper_size is None and paper_size is None:
        missing.append("paper_size (SceneInfo.paper_size is absent; supply paper_size)")
    if source_transform is None and source_to_page_transform is None:
        missing.append(
            "source_to_page_transform (supply an explicit six-value affine transform)"
        )
    if missing:
        raise GeometryResolutionError("Unable to resolve page geometry: " + "; ".join(missing))

    resolved_paper_size = _paper_size(
        paper_size if paper_size is not None else source_paper_size
    )
    resolved_transform = _affine_transform(
        source_to_page_transform
        if source_to_page_transform is not None
        else source_transform
    )
    return PageGeometry(
        paper_size=resolved_paper_size,
        source_to_page_transform=resolved_transform,
        paper_size_evidence=(
            (
                "Caller-supplied paper_size override replaced SceneInfo.paper_size."
                if source_paper_size is not None
                else "Caller-supplied paper_size; SceneInfo.paper_size was absent."
            )
            if paper_size is not None
            else "SceneInfo.paper_size from the parsed page."
        ),
        source_to_page_transform_evidence=(
            (
                "Caller-supplied source_to_page_transform override replaced parsed source "
                "metadata."
                if source_transform is not None
                else (
                    "Caller-supplied source_to_page_transform; parsed source metadata was "
                    "absent."
                )
            )
            if source_to_page_transform is not None
            else "Source-to-page transform from parsed source metadata."
        ),
    )
