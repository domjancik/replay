from dataclasses import replace

import pytest

from rm_redraw.parsing import GeometryResolutionError
from rm_redraw.parsing.model import (
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
from rm_redraw.pipeline import to_render_page


def _id(counter: int) -> CrdtIdentifier:
    return CrdtIdentifier(1, counter)


def _scene(item: int, block: int) -> SceneOrder:
    return SceneOrder(_id(item), _id(0), _id(0), 0, block)


def _parsed_page() -> NormalizedPage:
    lower, upper = _id(10), _id(20)
    first, second = _id(100), _id(200)
    empty_value = VersionedValue(_id(1), "")
    visible_value = VersionedValue(_id(2), True)
    identity = TransformResolution((1, 0, 0, 1, 0, 0), True, "test identity")
    groups = (
        NormalizedGroup(
            lower,
            lower,
            _id(1),
            lower,
            "layer",
            empty_value,
            visible_value,
            _scene(11, 1),
            identity,
            identity,
        ),
        NormalizedGroup(
            upper,
            upper,
            _id(1),
            upper,
            "layer",
            empty_value,
            visible_value,
            _scene(21, 2),
            identity,
            identity,
        ),
    )
    strokes = (
        NormalizedStroke(
            second,
            upper,
            upper,
            _scene(200, 4),
            None,
            EnumValue(17, "FINELINER_2"),
            EnumValue(6, "BLUE"),
            (1, 2, 3, 255),
            2.0,
            0.0,
            (NormalizedPoint(2, 3, 4, 5, 6, 7),),
        ),
        NormalizedStroke(
            first,
            lower,
            lower,
            _scene(100, 3),
            None,
            EnumValue(15, "BALLPOINT_2"),
            EnumValue(0, "BLACK"),
            None,
            1.5,
            0.0,
            (NormalizedPoint(8, 9, 10, 11, 12, 13),),
        ),
    )
    return NormalizedPage(
        "page",
        (1404, 1872),
        (1, 0, 0, 1, 0, 0),
        groups,
        strokes,
        (),
        (first, second),
        ReplayOrder("crdt-order", (second, first), "unverified"),
        PageMetadata(None, None, None, {}, (), None),
        PageDiagnostics((), ()),
    )


def test_parser_page_adapts_to_render_and_replay_contracts() -> None:
    page = to_render_page(_parsed_page())

    assert page.paper_size == (1404, 1872)
    assert page.compositing_order == ("1:10", "1:20")
    assert [stroke.stroke_id for stroke in page.strokes] == ["1:100", "1:200"]
    assert page.replay_order == ("1:200", "1:100")
    assert page.replay_strategy == "crdt-order"
    assert page.strokes[0].rgba == (0, 0, 0, 255)
    assert page.strokes[1].rgba == (1, 2, 3, 255)
    assert (page.strokes[0].tool_code, page.strokes[0].tool_name) == (15, "BALLPOINT_2")
    assert page.strokes[0].points[0].speed == 11


def test_missing_page_size_requires_explicit_override() -> None:
    parsed = _parsed_page()
    parsed = NormalizedPage(
        parsed.page_id,
        None,
        parsed.source_to_page_transform,
        parsed.groups,
        parsed.strokes,
        parsed.tombstones,
        parsed.compositing_order,
        parsed.replay_order,
        parsed.metadata,
        parsed.diagnostics,
    )

    page = to_render_page(parsed, paper_size=(1404, 1872))

    assert page.paper_size == (1404, 1872)


def test_missing_source_transform_requires_explicit_override() -> None:
    parsed = replace(_parsed_page(), source_to_page_transform=None)

    with pytest.raises(GeometryResolutionError, match="source_to_page_transform"):
        to_render_page(parsed)

    page = to_render_page(
        parsed,
        source_to_page_transform=(1, 0, 0, 1, 100, 200),
    )

    point = page.strokes[0].points[0]
    assert (point.x, point.y) == (108, 209)


def test_explicit_source_transform_projects_points_into_page_space() -> None:
    page = to_render_page(
        _parsed_page(),
        source_to_page_transform=(1, 0, 0, 1, 100, 200),
    )

    point = page.strokes[0].points[0]
    assert (point.x, point.y) == (108, 209)


def test_group_transform_is_applied_before_page_transform() -> None:
    parsed = _parsed_page()
    translated = replace(
        parsed.strokes[0],
        effective_transform=TransformResolution(
            (1, 0, 0, 1, -20, 30), True, "resolved test anchor"
        ),
    )
    parsed = replace(parsed, strokes=(translated, parsed.strokes[1]))

    page = to_render_page(
        parsed,
        source_to_page_transform=(2, 0, 0, 3, 100, 200),
    )

    stroke = next(stroke for stroke in page.strokes if stroke.stroke_id == "1:200")
    assert (stroke.points[0].x, stroke.points[0].y) == (64, 299)


def test_layer_visibility_is_preserved_for_render_and_replay() -> None:
    parsed = _parsed_page()
    hidden_upper = replace(
        parsed.groups[1],
        visible=VersionedValue(_id(3), False),
    )
    parsed = replace(parsed, groups=(parsed.groups[0], hidden_upper))

    page = to_render_page(parsed)

    assert [(group.group_id, group.visible) for group in page.groups] == [
        ("1:10", True),
        ("1:20", False),
    ]
