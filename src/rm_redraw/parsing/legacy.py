"""Bounded adapter for the pre-CRDT v5 layer/stroke stream.

Layout reference: https://github.com/akeil/rmtool#rm-lines-format
No paper dimensions or cross-layer chronology are encoded in this format.
"""

import base64
import math
import struct

from rmscene.scene_items import Pen, PenColor

from .model import (
    BlockDiagnostic,
    CrdtIdentifier,
    EnumValue,
    NormalizedGroup,
    NormalizedPage,
    NormalizedPoint,
    NormalizedStroke,
    PageDiagnostics,
    PageMetadata,
    ReplayOrder,
    SceneOrder,
    TransformResolution,
    VersionedValue,
)

HEADER = b"reMarkable .lines file, version=5          "
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
ZERO = CrdtIdentifier(0, 0)
ROOT = CrdtIdentifier(0, 1)


def enum_value(kind, code):
    try:
        return EnumValue(code, kind(code).name)
    except ValueError:
        return EnumValue(code, None)


def parse_v5(stream, page_id):
    data = stream.read(128 * 1024 * 1024 + 1)
    if len(data) > 128 * 1024 * 1024:
        raise ValueError("v5 page exceeds 128 MiB")
    if not data.startswith(HEADER):
        raise ValueError("Invalid v5 header")
    offset = len(HEADER)

    def read(fmt):
        nonlocal offset
        size = struct.calcsize(fmt)
        if offset + size > len(data):
            raise ValueError(f"Truncated v5 page at byte {offset}")
        result = struct.unpack_from(fmt, data, offset)
        offset += size
        return result

    layers = read("<I")[0]
    if layers > 4096 or layers * 4 > len(data) - offset:
        raise ValueError("Invalid v5 layer count")
    groups, strokes = [], []
    transform = TransformResolution(IDENTITY, True, "v5 top-left coordinates; no group transforms")
    for layer_index in range(layers):
        layer = CrdtIdentifier(0, layer_index + 2)
        count = read("<I")[0]
        if count > 1000000 or count * 24 > len(data) - offset:
            raise ValueError("Invalid v5 stroke count")
        groups.append(
            NormalizedGroup(
                node_id=layer,
                source_node_id=layer,
                parent_id=ROOT,
                layer_id=layer,
                kind="layer",
                label=VersionedValue(ZERO, f"Layer {layer_index + 1}"),
                visible=VersionedValue(ZERO, True),
                scene_order=SceneOrder(layer, ZERO, ZERO, 0, layer_index),
                local_transform=transform,
                effective_transform=transform,
                extra={"file_format": 5, "synthetic_id": True, "visibility_not_recorded": True},
            )
        )
        for stroke_index in range(count):
            tool, color, unknown1, thickness, unknown2, point_count = read("<IIIfII")
            if not math.isfinite(thickness) or thickness < 0:
                raise ValueError("Invalid v5 stroke thickness")
            if point_count > 5000000 or point_count * 24 > len(data) - offset:
                raise ValueError("Invalid or truncated v5 point count")
            points = []
            for _ in range(point_count):
                x, y, speed, direction, width, pressure = read("<6f")
                if not all(map(math.isfinite, (x, y, speed, direction, width, pressure))):
                    raise ValueError("Nonfinite v5 point channel")
                points.append(
                    NormalizedPoint(x, y, pressure, speed, direction, width, {"file_format": 5})
                )
            stroke_id = CrdtIdentifier(1, len(strokes) + 1)
            strokes.append(
                NormalizedStroke(
                    stroke_id=stroke_id,
                    parent_id=layer,
                    layer_id=layer,
                    scene_order=SceneOrder(stroke_id, ZERO, ZERO, 0, len(strokes)),
                    move_id=None,
                    tool=enum_value(Pen, tool),
                    color=enum_value(PenColor, color),
                    color_rgba=None,
                    thickness_scale=thickness,
                    starting_length=0,
                    points=tuple(points),
                    effective_transform=transform,
                    extra={
                        "file_format": 5,
                        "synthetic_id": True,
                        "layer_index": layer_index,
                        "stroke_index": stroke_index,
                        "legacy_unknown_fields": [unknown1, unknown2],
                    },
                )
            )
    order = tuple(s.stroke_id for s in strokes)
    tail = data[offset:]
    warnings = [
        "v5 file order is layer-major, not chronology; IDs are synthetic. "
        "Paper size and layer visibility are not encoded."
    ]
    if tail:
        warnings.append("Unparsed v5 trailing bytes retained in diagnostics.")
    diagnostics = PageDiagnostics(
        (
            BlockDiagnostic(
                0,
                5,
                "LegacyV5",
                False,
                None,
                None,
                base64.b64encode(tail).decode() if tail else None,
                None,
                {"file_format": 5, "layers": layers, "source_coordinate_origin": "top-left"},
            ),
        ),
        tuple(warnings),
    )
    return NormalizedPage(
        page_id=page_id,
        paper_size=None,
        source_to_page_transform=IDENTITY,
        groups=tuple(groups),
        strokes=tuple(strokes),
        tombstones=(),
        compositing_order=order,
        replay_order=ReplayOrder(
            "scene-order", order, "v5 stored layer/stroke order, not chronology"
        ),
        metadata=PageMetadata(None, None, None, {}, (), None),
        diagnostics=diagnostics,
    )
