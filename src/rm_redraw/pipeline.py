"""Explicit adapters between parser output and the baseline render/replay model."""

from __future__ import annotations

import math
from collections.abc import Mapping

from rm_redraw.parsing.geometry import resolve_page_geometry
from rm_redraw.parsing.model import NormalizedPage as ParsedPage
from rm_redraw.parsing.model import NormalizedPoint as ParsedPoint
from rm_redraw.parsing.model import NormalizedStroke as ParsedStroke
from rm_redraw.rendering.types import (
    Color,
    NormalizedGroup,
    NormalizedPage,
    NormalizedPoint,
    NormalizedStroke,
)

# Black/gray/blue/red agree across native 3.28 exports of six tool families.
# Yellow is measured on highlighter exports. Other entries remain provisional;
# explicit source RGBA and caller palettes win.
PALETTE_PROFILE = "native-basic-3.28-v1"
PALETTE_CALIBRATED_CODES = (0, 1, 3, 6, 7)
DEFAULT_PALETTE: Mapping[int, Color] = {
    0: (0, 0, 0, 255),
    1: (144, 144, 144, 255),
    2: (255, 255, 255, 255),
    3: (254, 253, 96, 255),
    4: (0, 128, 0, 255),
    5: (255, 105, 180, 255),
    6: (48, 74, 224, 255),
    7: (194, 49, 50, 255),
    8: (128, 128, 128, 255),
    9: (253, 227, 0, 128),
    10: (0, 170, 80, 255),
    11: (0, 180, 190, 255),
    12: (210, 0, 150, 255),
    13: (255, 200, 0, 255),
}


def _stroke_id(stroke: ParsedStroke) -> str:
    return str(stroke.stroke_id)


def _transform_xy(
    matrix: tuple[float, float, float, float, float, float],
    x: float,
    y: float,
) -> tuple[float, float]:
    a, b, c, d, e, f = matrix
    return a * x + c * y + e, b * x + d * y + f


def _project_point(
    point: ParsedPoint,
    group_transform: tuple[float, float, float, float, float, float],
    page_transform: tuple[float, float, float, float, float, float],
) -> NormalizedPoint:
    group_x, group_y = _transform_xy(group_transform, point.x, point.y)
    page_x, page_y = _transform_xy(page_transform, group_x, group_y)
    legacy = point.extra.get("file_format") == 5
    return NormalizedPoint(
        page_x,
        page_y,
        float(point.pressure) * (255 if legacy else 1),
        float(point.speed) * (4 if legacy else 1),
        float(point.direction) * (255 / (2 * math.pi) if legacy else 1),
        float(point.width) * (4 if legacy else 1),
        point.extra,
    )


def to_render_page(
    page: ParsedPage,
    *,
    paper_size: tuple[float, float] | None = None,
    source_to_page_transform: tuple[float, float, float, float, float, float] | None = None,
    palette: Mapping[int, Color] = DEFAULT_PALETTE,
) -> NormalizedPage:
    """Project lossless parser output into the deliberately smaller render model."""
    geometry = resolve_page_geometry(
        page,
        paper_size=paper_size,
        source_to_page_transform=source_to_page_transform,
    )
    resolved_size = geometry.paper_size
    transform = geometry.source_to_page_transform

    layer_ids: list[str] = []
    layer_visibility: dict[str, bool] = {}
    for group in page.groups:
        layer_id = str(group.layer_id)
        if layer_id not in layer_ids:
            layer_ids.append(layer_id)
            layer_visibility[layer_id] = True
        if group.kind == "layer" and str(group.node_id) == layer_id:
            layer_visibility[layer_id] = bool(group.visible.value)

    rank = {item_id: index for index, item_id in enumerate(page.compositing_order)}
    ordered_strokes = sorted(
        page.strokes,
        key=lambda stroke: rank.get(stroke.stroke_id, len(rank) + stroke.scene_order.block_index),
    )
    strokes = tuple(
        NormalizedStroke(
            stroke_id=_stroke_id(stroke),
            group_id=str(stroke.layer_id),
            rgba=stroke.color_rgba or palette[stroke.color.code],
            thickness_scale=stroke.thickness_scale,
            points=tuple(
                _project_point(point, stroke.effective_transform.matrix, transform)
                for point in stroke.points
            ),
            tool_code=stroke.tool.code,
            tool_name=stroke.tool.name,
        )
        for stroke in ordered_strokes
    )
    return NormalizedPage(
        page_id=page.page_id,
        paper_size=(float(resolved_size[0]), float(resolved_size[1])),
        groups=tuple(
            NormalizedGroup(layer_id, layer_visibility[layer_id]) for layer_id in layer_ids
        ),
        strokes=strokes,
        compositing_order=tuple(layer_ids),
        replay_order=tuple(str(item_id) for item_id in page.replay_order.stroke_ids),
        replay_strategy=page.replay_order.strategy,
        replay_evidence=page.replay_order.evidence,
    )
