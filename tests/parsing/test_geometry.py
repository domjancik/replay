from __future__ import annotations

from types import SimpleNamespace

import pytest

from rm_redraw.parsing import GeometryResolutionError, resolve_page_geometry


def _page(
    *,
    paper_size: tuple[int, int] | None,
    source_to_page_transform: tuple[float, float, float, float, float, float] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        paper_size=paper_size,
        source_to_page_transform=source_to_page_transform,
    )


def test_caller_geometry_overrides_source_values_and_carries_evidence() -> None:
    page = _page(
        paper_size=(1620, 2160),
        source_to_page_transform=(1.0, 0.0, 0.0, 1.0, 12.0, 34.0),
    )

    geometry = resolve_page_geometry(
        page,
        paper_size=(1404, 1872),
        source_to_page_transform=(1.0, 0.0, 0.0, 1.0, 702.0, 0.0),
    )

    assert geometry.paper_size == (1404, 1872)
    assert geometry.source_to_page_transform == (1.0, 0.0, 0.0, 1.0, 702.0, 0.0)
    assert geometry.paper_size_evidence == (
        "Caller-supplied paper_size override replaced SceneInfo.paper_size."
    )
    assert geometry.source_to_page_transform_evidence == (
        "Caller-supplied source_to_page_transform override replaced parsed source metadata."
    )


def test_source_geometry_is_used_when_caller_provides_no_override() -> None:
    geometry = resolve_page_geometry(
        _page(
            paper_size=(1620, 2160),
            source_to_page_transform=(1.0, 0.0, 0.0, 1.0, 12.0, 34.0),
        )
    )

    assert geometry.paper_size == (1620, 2160)
    assert geometry.source_to_page_transform == (1.0, 0.0, 0.0, 1.0, 12.0, 34.0)
    assert geometry.paper_size_evidence == "SceneInfo.paper_size from the parsed page."
    assert geometry.source_to_page_transform_evidence == (
        "Source-to-page transform from parsed source metadata."
    )


def test_caller_values_resolve_geometry_missing_from_source() -> None:
    page = _page(paper_size=None)

    geometry = resolve_page_geometry(
        page,
        paper_size=(1404, 1872),
        source_to_page_transform=(1, 0, 0, 1, 702, 0),
    )

    assert geometry.paper_size == (1404, 1872)
    assert geometry.source_to_page_transform == (1.0, 0.0, 0.0, 1.0, 702.0, 0.0)
    assert geometry.paper_size_evidence == (
        "Caller-supplied paper_size; SceneInfo.paper_size was absent."
    )
    assert geometry.source_to_page_transform_evidence == (
        "Caller-supplied source_to_page_transform; parsed source metadata was absent."
    )


def test_source_paper_size_combines_with_caller_transform() -> None:
    geometry = resolve_page_geometry(
        _page(paper_size=(1620, 2160)),
        source_to_page_transform=(1, 0, 0, 1, 810, 0),
    )

    assert geometry.paper_size == (1620, 2160)
    assert geometry.source_to_page_transform == (1.0, 0.0, 0.0, 1.0, 810.0, 0.0)
    assert "SceneInfo.paper_size" in geometry.paper_size_evidence
    assert "Caller-supplied" in geometry.source_to_page_transform_evidence


def test_unresolved_geometry_names_every_required_override() -> None:
    with pytest.raises(GeometryResolutionError) as exc_info:
        resolve_page_geometry(_page(paper_size=None))

    message = str(exc_info.value)
    assert "paper_size" in message
    assert "source_to_page_transform" in message
    assert "SceneInfo.paper_size" in message
    assert "six-value affine" in message


@pytest.mark.parametrize(
    ("paper_size", "transform", "expected"),
    [
        ((0, 1872), (1, 0, 0, 1, 0, 0), "positive"),
        ((1404, 1872), (1, 0, 0, 1, 0), "six finite numbers"),
        ((1404, 1872), (1, 0, 0, 1, float("inf"), 0), "six finite numbers"),
    ],
)
def test_invalid_geometry_is_rejected_actionably(
    paper_size: tuple[int, int],
    transform: tuple[float, ...],
    expected: str,
) -> None:
    with pytest.raises(ValueError, match=expected):
        resolve_page_geometry(
            _page(paper_size=None),
            paper_size=paper_size,
            source_to_page_transform=transform,
        )
