import struct
from io import BytesIO

import pytest

from rm_redraw.parsing import parse_page
from rm_redraw.pipeline import to_render_page


def legacy_page():
    header = b"reMarkable .lines file, version=5          "
    point = struct.pack("<6f", 20, 30, 2, 1, 3, 0.5)
    stroke = (
        struct.pack("<IIIfII", 17, 0, 91, 2, 92, 2) + point + struct.pack("<6f", 60, 70, 3, 2, 4, 1)
    )
    return header + struct.pack("<II", 2, 1) + stroke + struct.pack("<I", 0)


def test_v5_keeps_raw_channels_unknown_fields_and_explicit_file_order():
    page = parse_page(BytesIO(legacy_page()), page_id="old-cloud")
    assert len(page.groups) == 2
    assert len(page.strokes) == 1
    stroke = page.strokes[0]
    assert (stroke.points[0].width, stroke.points[0].pressure) == (3, 0.5)
    assert stroke.extra["legacy_unknown_fields"] == [91, 92]
    assert page.replay_order.strategy == "scene-order"
    assert "not chronology" in page.replay_order.evidence
    assert page.source_to_page_transform == (1, 0, 0, 1, 0, 0)
    assert page.paper_size is None
    rendered = to_render_page(page, paper_size=(1404, 1872))
    point = rendered.strokes[0].points[0]
    assert (point.x, point.y) == (20, 30)
    assert (point.width, point.pressure, point.speed) == (12, 127.5, 8)


@pytest.mark.parametrize(
    "data", [legacy_page()[:-1], legacy_page()[:43] + struct.pack("<I", 0xFFFFFFFF)]
)
def test_v5_rejects_truncated_or_unbounded_counts(data):
    with pytest.raises(ValueError, match="v5"):
        parse_page(BytesIO(data), page_id="bad")


def test_v5_static_and_final_frame_are_identical_and_nonblank():
    from rm_redraw.rendering.pillow import PillowRenderer
    from rm_redraw.rendering.types import RenderOptions, VisibilityState

    page = to_render_page(
        parse_page(BytesIO(legacy_page()), page_id="legacy"), paper_size=(100, 100)
    )
    renderer = PillowRenderer()
    static = renderer.render_static(page, RenderOptions())
    final = renderer.render(page, RenderOptions(), VisibilityState(frozenset(page.replay_order)))
    assert static.tobytes() == final.tobytes()
    assert static.getpixel((20, 30))[:3] != (255, 255, 255)


def test_v5_preserves_trailing_data_and_unknown_tools():
    data = bytearray(legacy_page())
    struct.pack_into("<I", data, 51, 999)
    page = parse_page(BytesIO(data + b"unknown"), page_id="extra")
    assert page.strokes[0].tool.code == 999
    assert page.strokes[0].tool.name is None
    assert page.diagnostics.blocks[0].extra_data_base64 == "dW5rbm93bg=="


