"""A deterministic Pillow baseline for simple opaque or translucent strokes."""

from __future__ import annotations

from PIL import Image, ImageDraw

from .geometry import prefix_points
from .types import (
    NormalizedPage,
    NormalizedPoint,
    NormalizedStroke,
    RenderOptions,
    Viewport,
    VisibilityState,
)


class PillowRenderer:
    """Renders every frame from immutable visibility state and layer compositing."""

    def render(
        self,
        page: NormalizedPage,
        options: RenderOptions,
        visibility: VisibilityState,
    ) -> Image.Image:
        viewport = _resolve_viewport(page, options)
        image = Image.new("RGBA", (viewport.width, viewport.height), options.background)
        strokes_by_group = {group.group_id: [] for group in page.groups}
        for stroke in page.strokes:
            strokes_by_group.setdefault(stroke.group_id, []).append(stroke)

        for group_id in page.compositing_order:
            layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
            for stroke in strokes_by_group.get(group_id, []):
                points = _visible_points(stroke, visibility)
                if points:
                    _draw_stroke(layer, points, stroke, page, viewport)
            image.alpha_composite(layer)
        return image

    def render_static(self, page: NormalizedPage, options: RenderOptions) -> Image.Image:
        return self.render(
            page,
            options,
            VisibilityState(frozenset(stroke.stroke_id for stroke in page.strokes)),
        )


def _resolve_viewport(page: NormalizedPage, options: RenderOptions) -> Viewport:
    if options.viewport is not None:
        return options.viewport
    if page.paper_size is None:
        raise ValueError("a page without paper_size requires an explicit viewport")
    return Viewport(round(page.paper_size[0]), round(page.paper_size[1]))


def _visible_points(
    stroke: NormalizedStroke, visibility: VisibilityState
) -> tuple[NormalizedPoint, ...]:
    if stroke.stroke_id in visibility.completed_stroke_ids:
        return stroke.points
    if stroke.stroke_id == visibility.active_stroke_id:
        return prefix_points(stroke, visibility.active_progress)
    return ()


def _draw_stroke(
    layer: Image.Image,
    points: tuple[NormalizedPoint, ...],
    stroke: NormalizedStroke,
    page: NormalizedPage,
    viewport: Viewport,
) -> None:
    if page.paper_size is None:
        raise ValueError("a page without paper_size requires an explicit transform")
    scale_x = viewport.width / page.paper_size[0]
    scale_y = viewport.height / page.paper_size[1]
    scale = (scale_x + scale_y) / 2
    coordinates = [(point.x * scale_x, point.y * scale_y) for point in points]
    width = max(1, round(stroke.thickness_scale * scale))
    draw = ImageDraw.Draw(layer)
    if len(coordinates) == 1:
        x, y = coordinates[0]
        radius = width / 2
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=stroke.rgba)
    else:
        draw.line(coordinates, fill=stroke.rgba, width=width, joint="curve")
