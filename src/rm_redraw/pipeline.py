"""Explicit adapters between parser output and the baseline render/replay model."""

from __future__ import annotations

from collections.abc import Mapping

from rm_redraw.parsing.model import NormalizedPage as ParsedPage
from rm_redraw.parsing.model import NormalizedStroke as ParsedStroke
from rm_redraw.rendering.types import (
    Color,
    NormalizedGroup,
    NormalizedPage,
    NormalizedPoint,
    NormalizedStroke,
)

DEFAULT_PALETTE: Mapping[int, Color] = {
    0: (0, 0, 0, 255),
    1: (128, 128, 128, 255),
    2: (255, 255, 255, 255),
    3: (253, 227, 0, 255),
    4: (0, 128, 0, 255),
    5: (255, 105, 180, 255),
    6: (0, 82, 204, 255),
    7: (204, 0, 0, 255),
    8: (128, 128, 128, 255),
    9: (253, 227, 0, 128),
    10: (0, 170, 80, 255),
    11: (0, 180, 190, 255),
    12: (210, 0, 150, 255),
    13: (255, 200, 0, 255),
}


def _stroke_id(stroke: ParsedStroke) -> str:
    return str(stroke.stroke_id)


def to_render_page(
    page: ParsedPage,
    *,
    paper_size: tuple[float, float] | None = None,
    source_to_page_transform: tuple[float, float, float, float, float, float] | None = None,
    palette: Mapping[int, Color] = DEFAULT_PALETTE,
) -> NormalizedPage:
    """Project lossless parser output into the deliberately smaller render model."""
    resolved_size = page.paper_size if page.paper_size is not None else paper_size
    if resolved_size is None:
        raise ValueError("paper_size is absent from the source and must be supplied explicitly")
    transform = source_to_page_transform or page.source_to_page_transform
    a, b, c, d, e, f = transform

    layer_ids: list[str] = []
    for group in page.groups:
        layer_id = str(group.layer_id)
        if layer_id not in layer_ids:
            layer_ids.append(layer_id)

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
                NormalizedPoint(
                    a * point.x + c * point.y + e,
                    b * point.x + d * point.y + f,
                    float(point.pressure),
                    float(point.speed),
                    float(point.direction),
                    float(point.width),
                    point.extra,
                )
                for point in stroke.points
            ),
        )
        for stroke in ordered_strokes
    )
    return NormalizedPage(
        page_id=page.page_id,
        paper_size=(float(resolved_size[0]), float(resolved_size[1])),
        groups=tuple(NormalizedGroup(layer_id) for layer_id in layer_ids),
        strokes=strokes,
        compositing_order=tuple(layer_ids),
        replay_order=tuple(str(item_id) for item_id in page.replay_order.stroke_ids),
        replay_strategy=page.replay_order.strategy,
        replay_evidence=page.replay_order.evidence,
    )
