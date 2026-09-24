"""A deterministic Pillow baseline for simple opaque or translucent strokes."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor, hypot, sqrt

from PIL import Image, ImageChops, ImageDraw

from .geometry import prefix_points
from .simple import draw_simple
from .texture import TEXTURED_CODES, TEXTURED_NAMES, draw_texture
from .types import (
    NormalizedPage,
    NormalizedPoint,
    NormalizedStroke,
    RenderOptions,
    Viewport,
    VisibilityState,
)

# The five-point width/intensity profile follows the MIT-licensed remarkable-rm
# reference renderer. This Pillow-specific multiplier is provisionally calibrated
# against the isolated three-stroke BALLPOINT_2 native export.
_BALLPOINT_RASTER_WIDTH_SCALE = 0.75


@dataclass
class _PrefixCache:
    page: NormalizedPage
    options: RenderOptions
    viewport: Viewport
    strokes: tuple[NormalizedStroke, ...]
    stroke_ids: tuple[str, ...]
    base: Image.Image
    layer: Image.Image
    completed_count: int = 0
    group_id: str | None = None


class PillowRenderer:
    """Render immutable visibility with a bounded, exact append-prefix cache.

    Only two canvases persist: completed lower layers and the current layer's
    completed strokes. Active ink is drawn on a disposable copy. Nonprefix
    visibility falls back to a stateless render, never reordered painting.
    """

    def __init__(self) -> None:
        self._prefix_cache: _PrefixCache | None = None

    def render(
        self,
        page: NormalizedPage,
        options: RenderOptions,
        visibility: VisibilityState,
    ) -> Image.Image:
        cache = self._prefix_cache
        if cache is None or cache.page is not page or cache.options != options:
            cache = self._new_prefix_cache(page, options)
        visible_ids = frozenset(cache.stroke_ids)
        completed = visibility.completed_stroke_ids & visible_ids
        count = len(completed)
        active = visibility.active_stroke_id
        if active in visibility.completed_stroke_ids:
            active = None
        valid_prefix = (
            len(visible_ids) == len(cache.stroke_ids)
            and completed == frozenset(cache.stroke_ids[:count])
            and (
                active is None or (count < len(cache.strokes) and active == cache.stroke_ids[count])
            )
        )
        if not valid_prefix:
            self._prefix_cache = None
            return self._render_uncached(page, options, visibility)
        if count < cache.completed_count:
            cache = self._new_prefix_cache(page, options)
        self._prefix_cache = cache

        for stroke in cache.strokes[cache.completed_count : count]:
            if stroke.group_id != cache.group_id:
                cache.base.alpha_composite(cache.layer)
                cache.layer = Image.new("RGBA", cache.base.size, (0, 0, 0, 0))
                cache.group_id = stroke.group_id
            if stroke.points:
                _draw_stroke(cache.layer, stroke.points, stroke, page, cache.viewport)
        cache.completed_count = count

        result = cache.base.copy()
        if active is None:
            result.alpha_composite(cache.layer)
            return result
        stroke = cache.strokes[count]
        if stroke.group_id == cache.group_id:
            active_layer = cache.layer.copy()
        else:
            result.alpha_composite(cache.layer)
            active_layer = Image.new("RGBA", result.size, (0, 0, 0, 0))
        points = _visible_points(stroke, visibility)
        if points:
            _draw_stroke(active_layer, points, stroke, page, cache.viewport)
        result.alpha_composite(active_layer)
        return result

    @staticmethod
    def _new_prefix_cache(page: NormalizedPage, options: RenderOptions) -> _PrefixCache:
        viewport = _resolve_viewport(page, options)
        visible_groups = {group.group_id for group in page.groups if group.visible}
        ordered = tuple(
            stroke
            for group_id in page.compositing_order
            if group_id in visible_groups
            for stroke in page.strokes
            if stroke.group_id == group_id
        )
        size = (viewport.width, viewport.height)
        return _PrefixCache(
            page,
            options,
            viewport,
            ordered,
            tuple(stroke.stroke_id for stroke in ordered),
            Image.new("RGBA", size, options.background),
            Image.new("RGBA", size, (0, 0, 0, 0)),
        )

    @staticmethod
    def _render_uncached(
        page: NormalizedPage,
        options: RenderOptions,
        visibility: VisibilityState,
    ) -> Image.Image:
        viewport = _resolve_viewport(page, options)
        image = Image.new("RGBA", (viewport.width, viewport.height), options.background)
        strokes_by_group = {group.group_id: [] for group in page.groups}
        for stroke in page.strokes:
            strokes_by_group.setdefault(stroke.group_id, []).append(stroke)

        visible_groups = {group.group_id for group in page.groups if group.visible}
        for group_id in page.compositing_order:
            if group_id not in visible_groups:
                continue
            layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
            for stroke in strokes_by_group.get(group_id, []):
                points = _visible_points(stroke, visibility)
                if points:
                    _draw_stroke(layer, points, stroke, page, viewport)
            image.alpha_composite(layer)
        return image

    def render_static(self, page: NormalizedPage, options: RenderOptions) -> Image.Image:
        return self._render_uncached(
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
    is_simple = stroke.tool_code in {16, 17, 18} or stroke.tool_name in {
        "MARKER_2",
        "FINELINER_2",
        "HIGHLIGHTER_2",
    }
    if is_simple:
        draw_simple(layer, points, stroke, scale_x, scale_y)
        return
    if stroke.tool_code in TEXTURED_CODES or stroke.tool_name in TEXTURED_NAMES:
        length = sum(hypot(b.x - a.x, b.y - a.y) for a, b in zip(points, points[1:], strict=False))
        draw_texture(layer, stroke, length, scale_x, scale_y)
        return
    if stroke.tool_code == 6 or stroke.tool_name == "ERASER":
        _erase_stroke(
            layer,
            coordinates,
            [
                max(0.0, point.width / 4.0) * scale if point.width is not None else scale
                for point in points
            ],
        )
        return
    if stroke.tool_code in {2, 15} or stroke.tool_name in {"BALLPOINT", "BALLPOINT_2"}:
        _draw_ballpoint(layer, coordinates, points, stroke, scale)
        return
    width = max(1, round(stroke.thickness_scale * scale))
    draw = ImageDraw.Draw(layer)
    if len(coordinates) == 1:
        x, y = coordinates[0]
        radius = width / 2
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=stroke.rgba)
    else:
        draw.line(coordinates, fill=stroke.rgba, width=width, joint="curve")


def _erase_stroke(
    layer: Image.Image,
    coordinates: list[tuple[float, float]],
    widths: list[float],
) -> None:
    """Clear layer-local ink using captured native raw quarter-unit widths.

    Firmware 3.28 fixture evidence: thickness does not affect tool-6 width;
    fewer than two distinct positions paint nothing. Missing widths use a
    conservative one-source-unit fallback, not a native-calibrated profile.
    """
    if len(set(coordinates)) < 2:
        return

    supersample = 4
    radius = max(widths, default=0.0) / 2.0
    if radius <= 0:
        return
    # A rotated square cap reaches sqrt(2) times its half-width on either axis.
    margin = sqrt(2) * radius + 2.0
    left = max(0, floor(min(x for x, _ in coordinates) - margin))
    top = max(0, floor(min(y for _, y in coordinates) - margin))
    right = min(layer.width, ceil(max(x for x, _ in coordinates) + margin) + 1)
    bottom = min(layer.height, ceil(max(y for _, y in coordinates) + margin) + 1)
    if right <= left or bottom <= top:
        return

    mask = Image.new(
        "L",
        ((right - left) * supersample, (bottom - top) * supersample),
        0,
    )
    local_coordinates = [
        ((x - left) * supersample, (y - top) * supersample) for x, y in coordinates
    ]
    if len(set(widths)) == 1:
        _draw_square_polyline(mask, local_coordinates, max(1, round(widths[0] * supersample)), 255)
    else:
        _draw_variable_eraser(mask, local_coordinates, [width * supersample for width in widths])
    mask = mask.resize((right - left, bottom - top), Image.Resampling.LANCZOS)

    alpha = layer.getchannel("A")
    region = alpha.crop((left, top, right, bottom))
    erased = ImageChops.multiply(region, ImageChops.invert(mask))
    alpha.paste(erased, (left, top))
    layer.putalpha(alpha)


def _draw_variable_eraser(
    image: Image.Image,
    coordinates: list[tuple[float, float]],
    widths: list[float],
) -> None:
    """Provisional variable-width envelope; native join/taper parity is unverified."""
    draw = ImageDraw.Draw(image)
    segments = [
        (i, a, b)
        for i, (a, b) in enumerate(zip(coordinates, coordinates[1:], strict=False))
        if a != b
    ]
    for number, (i, a, b) in enumerate(segments):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = hypot(dx, dy)
        ux, uy = dx / length, dy / length
        r0, r1 = widths[i] / 2, widths[i + 1] / 2
        start, end = a, b
        draw.polygon(
            [
                (start[0] - uy * r0, start[1] + ux * r0),
                (start[0] + uy * r0, start[1] - ux * r0),
                (end[0] + uy * r1, end[1] - ux * r1),
                (end[0] - uy * r1, end[1] + ux * r1),
            ],
            fill=255,
        )
        if number == 0:
            _draw_square_cap(draw, a, b, r0, 255)
        if number == len(segments) - 1:
            _draw_square_cap(draw, b, a, r1, 255)
        if number < len(segments) - 1:
            draw.ellipse((b[0] - r1, b[1] - r1, b[0] + r1, b[1] + r1), fill=255)


def _draw_square_polyline(
    image: Image.Image,
    coordinates: list[tuple[float, float]],
    width: int,
    fill: int,
) -> None:
    # Repeated samples carry no new geometry and must not set the cap direction.
    coordinates = [
        point
        for index, point in enumerate(coordinates)
        if index == 0 or point != coordinates[index - 1]
    ]
    draw = ImageDraw.Draw(image)
    radius = width / 2.0
    if len(coordinates) == 1:
        x, y = coordinates[0]
        draw.rectangle((x - radius, y - radius, x + radius, y + radius), fill=fill)
        return

    draw.line(coordinates, fill=fill, width=width, joint="curve")
    _draw_square_cap(draw, coordinates[0], coordinates[1], radius, fill)
    _draw_square_cap(draw, coordinates[-1], coordinates[-2], radius, fill)


def _draw_square_cap(
    draw: ImageDraw.ImageDraw,
    endpoint: tuple[float, float],
    neighbour: tuple[float, float],
    radius: float,
    fill: int,
) -> None:
    dx = endpoint[0] - neighbour[0]
    dy = endpoint[1] - neighbour[1]
    length = hypot(dx, dy)
    if length == 0:
        x, y = endpoint
        draw.rectangle((x - radius, y - radius, x + radius, y + radius), fill=fill)
        return
    along_x = dx / length * radius
    along_y = dy / length * radius
    across_x = -dy / length * radius
    across_y = dx / length * radius
    draw.polygon(
        (
            (endpoint[0] - across_x, endpoint[1] - across_y),
            (endpoint[0] + across_x, endpoint[1] + across_y),
            (endpoint[0] + along_x + across_x, endpoint[1] + along_y + across_y),
            (endpoint[0] + along_x - across_x, endpoint[1] + along_y - across_y),
        ),
        fill=fill,
    )


def _draw_ballpoint(
    layer: Image.Image,
    coordinates: list[tuple[float, float]],
    points: tuple[NormalizedPoint, ...],
    stroke: NormalizedStroke,
    scale: float,
) -> None:
    """Render v1/v2 ballpoint samples in the native five-point profile."""
    if any(point.width is None or point.speed is None for point in points):
        _draw_round_polyline(
            layer,
            coordinates,
            max(1, round(stroke.thickness_scale * scale)),
            stroke.rgba,
        )
        return

    supersample = 2
    profile_widths = [
        _ballpoint_width(points[start]) * scale * _BALLPOINT_RASTER_WIDTH_SCALE
        for start in range(0, len(points), 5)
    ]
    margin = max(profile_widths, default=1.0) + 2.0
    left = max(0, int(min(x for x, _ in coordinates) - margin))
    top = max(0, int(min(y for _, y in coordinates) - margin))
    right = min(layer.width, int(max(x for x, _ in coordinates) + margin) + 1)
    bottom = min(layer.height, int(max(y for _, y in coordinates) + margin) + 1)
    if right <= left or bottom <= top:
        return
    sampled = Image.new(
        "RGBA",
        ((right - left) * supersample, (bottom - top) * supersample),
        (0, 0, 0, 0),
    )
    sampled_coordinates = [
        ((x - left) * supersample, (y - top) * supersample) for x, y in coordinates
    ]
    previous: tuple[float, float] | None = None
    for start in range(0, len(points), 5):
        segment_points = points[start : start + 5]
        segment_coordinates = sampled_coordinates[start : start + 5]
        if previous is not None:
            segment_coordinates = [previous, *segment_coordinates]
        profile_point = segment_points[0]
        width = max(
            1,
            round(
                _ballpoint_width(profile_point)
                * scale
                * _BALLPOINT_RASTER_WIDTH_SCALE
                * supersample
            ),
        )
        color = _ballpoint_color(profile_point, stroke.rgba)
        _draw_round_polyline(sampled, segment_coordinates, width, color)
        previous = segment_coordinates[-1]
    antialiased = sampled.resize(
        (right - left, bottom - top),
        resample=Image.Resampling.LANCZOS,
    )
    layer.alpha_composite(antialiased, dest=(left, top))


def _ballpoint_width(point: NormalizedPoint) -> float:
    pressure = min(255.0, max(0.0, point.pressure))
    assert point.width is not None
    assert point.speed is not None
    return max(
        0.25,
        0.5 + pressure / 255.0 + point.width / 4.0 - 0.5 * (point.speed / 4.0 / 50.0),
    )


def _ballpoint_color(
    point: NormalizedPoint,
    rgba: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    assert point.speed is not None
    pressure = min(255.0, max(0.0, point.pressure))
    intensity = 0.1 * -(point.speed / 4.0 / 35.0) + 1.2 * (pressure / 255.0) + 0.5
    intensity = min(1.0, max(0.0, intensity))
    fade = min(abs(intensity - 1.0), 60.0 / 255.0)
    red, green, blue, alpha = rgba
    return (
        round(red + (255 - red) * fade),
        round(green + (255 - green) * fade),
        round(blue + (255 - blue) * fade),
        alpha,
    )


def _draw_round_polyline(
    layer: Image.Image,
    coordinates: list[tuple[float, float]],
    width: int,
    color: tuple[int, int, int, int],
) -> None:
    if not coordinates:
        return
    draw = ImageDraw.Draw(layer)
    if len(coordinates) > 1:
        draw.line(coordinates, fill=color, width=width, joint="curve")
    radius = width / 2.0
    for x, y in {coordinates[0], coordinates[-1]}:
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
