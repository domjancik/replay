"""Measured fineliner/highlighter and provisional marker from the 3.28 capture.

Grid even columns establish quarter-unit raw widths independent of thickness,
pressure, speed and direction. Native PDF operators establish round fineliner
caps/joins and butt highlighter caps/bevel joins. Supplement taps distinguish
single points from coincident fineliner pairs. The fineliner dynamics PDF proves
first-sample width. Variable highlighter/marker envelopes remain interpolation
models, not claims of exact native tessellation.
"""

from math import ceil, floor, hypot

import numpy as np
from PIL import Image, ImageDraw

from .types import NormalizedPoint, NormalizedStroke

# A provisional smooth envelope, not the native marker's irregular polygon.
# Capture grid page9 even-column controls: width24 gives mean body coverage
# ~4.3 source pixels and width96 ~18.3; 0.75 of quarter-unit width is the
# coarse common fit. Width4 and stationary paths are captured negative controls.
_MARKER_ENVELOPE_SCALE = 0.75


def draw_simple(
    layer: Image.Image,
    points: tuple[NormalizedPoint, ...],
    stroke: NormalizedStroke,
    scale_x: float,
    scale_y: float,
) -> None:
    if len(points) < 2:
        return
    highlighter = stroke.tool_code == 18 or stroke.tool_name == "HIGHLIGHTER_2"
    marker = stroke.tool_code == 16 or stroke.tool_name == "MARKER_2"
    coords = [(p.x * scale_x, p.y * scale_y) for p in points]
    if (highlighter or marker) and len(set(coords)) < 2:
        return
    scale = (scale_x + scale_y) / 2
    widths = [
        max(0, p.width / 4 if p.width is not None else stroke.thickness_scale) * scale
        for p in points
    ]
    if stroke.tool_code == 17 or stroke.tool_name == "FINELINER_2":
        # Dynamics PDF page17 has one w operand per complete stroked path:
        # raw4->80,80->4,4->80->4 become source widths1,20,1 respectively.
        # Only the first sample sets fineliner width, including partial replay.
        widths = [widths[0]] * len(widths)
    if marker:
        widths = [
            0 if p.width is not None and p.width <= 4 else w * _MARKER_ENVELOPE_SCALE
            for p, w in zip(points, widths, strict=True)
        ]
    margin = max(widths) / 2 + 3
    left = max(0, floor(min(x for x, y in coords) - margin))
    top = max(0, floor(min(y for x, y in coords) - margin))
    right = min(layer.width, ceil(max(x for x, y in coords) + margin))
    bottom = min(layer.height, ceil(max(y for x, y in coords) + margin))
    if right <= left or bottom <= top or not max(widths):
        return
    ss = 4
    mask = Image.new("L", ((right - left) * ss, (bottom - top) * ss), 0)
    draw = ImageDraw.Draw(mask)
    local = [((x - left) * ss, (y - top) * ss) for x, y in coords]
    radii = [w * ss / 2 for w in widths]
    previous_normal = None
    for i, (a, b) in enumerate(zip(local, local[1:], strict=False)):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = hypot(dx, dy)
        if not length:
            continue
        nx, ny = -dy / length, dx / length
        ra, rb = radii[i], radii[i + 1]
        draw.polygon(
            [
                (a[0] + nx * ra, a[1] + ny * ra),
                (a[0] - nx * ra, a[1] - ny * ra),
                (b[0] - nx * rb, b[1] - ny * rb),
                (b[0] + nx * rb, b[1] + ny * rb),
            ],
            fill=255,
        )
        if highlighter and previous_normal is not None:
            px, py = previous_normal
            draw.polygon(
                [
                    (a[0] + px * ra, a[1] + py * ra),
                    (a[0] + nx * ra, a[1] + ny * ra),
                    (a[0] - px * ra, a[1] - py * ra),
                    (a[0] - nx * ra, a[1] - ny * ra),
                ],
                fill=255,
            )
        previous_normal = nx, ny
    if not highlighter:
        for (x, y), r in zip(local, radii, strict=True):
            draw.ellipse((x - r, y - r, x + r, y + r), fill=255)
    mask = mask.resize((right - left, bottom - top), Image.Resampling.LANCZOS)
    if stroke.rgba[3] != 255:
        mask = mask.point(lambda a: round(a * stroke.rgba[3] / 255))
    ink = Image.new("RGBA", mask.size, stroke.rgba)
    ink.putalpha(mask)
    if highlighter:
        # The captured PDF uses Darken, not Multiply. Blend within the current
        # layer, respecting transparent backdrop pixels and applying coverage once.
        # Cross-layer blend-group equivalence is not established by these fixtures.
        background = np.asarray(layer.crop((left, top, right, bottom)), dtype=float) / 255
        source = np.asarray(ink, dtype=float) / 255
        sa, da = source[:, :, 3:4], background[:, :, 3:4]
        alpha = sa + da * (1 - sa)
        premultiplied = (
            sa * (1 - da) * source[:, :, :3]
            + sa * da * np.minimum(source[:, :, :3], background[:, :, :3])
            + (1 - sa) * da * background[:, :, :3]
        )
        rgb = np.divide(premultiplied, alpha, out=np.zeros_like(premultiplied), where=alpha > 0)
        result = np.rint(np.clip(np.concatenate((rgb, alpha), axis=2), 0, 1) * 255).astype(np.uint8)
        layer.paste(Image.fromarray(result), (left, top))
    else:
        layer.alpha_composite(ink, (left, top))
