from __future__ import annotations

import ast
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from rmscene import (
    CrdtId,
    CrdtSequenceItem,
    LwwValue,
    RootTextBlock,
    SceneGroupItemBlock,
    SceneLineItemBlock,
    SceneTreeBlock,
    TreeNodeBlock,
    simple_text_document,
    write_blocks,
)
from rmscene import (
    scene_items as si,
)

from rm_redraw.parsing import CrdtIdentifier, TextAnchorLayout, parse_page

END = CrdtId(0, 0)
TEXT_LAYER = CrdtId(0, 11)
ANCHOR_ID = CrdtId(1, 17)


def _anchored_page(
    *,
    pos_y: float = 234.0,
    anchors: tuple[CrdtId, ...] = (ANCHOR_ID,),
    anchor_type: int = 2,
) -> BytesIO:
    blocks = []
    for block in simple_text_document("\n\n"):
        if isinstance(block, RootTextBlock):
            block = replace(block, value=replace(block.value, pos_y=pos_y))
        blocks.append(block)
    for index, anchor_id in enumerate(anchors):
        group_id = CrdtId(40, 100 + index * 100)
        blocks.extend(
            [
                SceneTreeBlock(group_id, END, True, TEXT_LAYER),
                TreeNodeBlock(
                    si.Group(
                        group_id,
                        anchor_id=LwwValue(CrdtId(40, 110 + index * 100), anchor_id),
                        anchor_type=LwwValue(
                            CrdtId(40, 111 + index * 100), anchor_type
                        ),
                        anchor_threshold=LwwValue(
                            CrdtId(40, 112 + index * 100), 35.74803161621094
                        ),
                        anchor_origin_x=LwwValue(
                            CrdtId(40, 113 + index * 100), 400.0
                        ),
                    )
                ),
                SceneGroupItemBlock(
                    TEXT_LAYER,
                    CrdtSequenceItem(
                        CrdtId(40, 114 + index * 100), END, END, 0, group_id
                    ),
                ),
                SceneLineItemBlock(
                    group_id,
                    CrdtSequenceItem(
                        CrdtId(40, 115 + index * 100),
                        END,
                        END,
                        0,
                        si.Line(
                            color=si.PenColor.BLACK,
                            tool=si.Pen.BALLPOINT_2,
                            points=[si.Point(60.0, -10.0, 2, 0, 12, 0)],
                            thickness_scale=2.0,
                            starting_length=0.0,
                        ),
                    ),
                ),
            ]
        )
    data = BytesIO()
    write_blocks(data, blocks, options={"version": "3.27.3"})
    data.seek(0)
    return data


@pytest.mark.parametrize("pos_y", [214.0, 234.0, 254.0, 274.0])
def test_caller_layout_offset_is_added_to_raw_root_text_pos_y(pos_y: float) -> None:
    layout = TextAnchorLayout(
        offsets={CrdtIdentifier(1, 17): 91.25},
        evidence="native-equivalent synthetic layout",
    )

    page = parse_page(
        _anchored_page(pos_y=pos_y),
        page_id="layout-position",
        text_anchor_layout=layout,
    )

    group = next(group for group in page.groups if group.kind == "group")
    stroke = page.strokes[0]
    assert group.local_transform.matrix == (
        1.0,
        0.0,
        0.0,
        1.0,
        400.0,
        pos_y + 91.25,
    )
    assert group.local_transform.resolved is True
    assert "caller-supplied" in group.local_transform.evidence
    assert "native-equivalent synthetic layout" in group.local_transform.evidence
    assert stroke.effective_transform == group.effective_transform
    assert (stroke.points[0].x, stroke.points[0].y) == (60.0, -10.0)


@pytest.mark.parametrize("offset", [20.0, -20.0, 40.0, 94.453125])
def test_layout_offsets_are_followed_fully_without_threshold_arithmetic(
    offset: float,
) -> None:
    page = parse_page(
        _anchored_page(),
        page_id="threshold-independent",
        text_anchor_layout=TextAnchorLayout(
            {CrdtIdentifier(1, 17): offset}, "controlled native evidence"
        ),
    )

    group = next(group for group in page.groups if group.kind == "group")
    assert group.local_transform.matrix[-2:] == (400.0, 234.0 + offset)
    assert group.local_transform.resolved is True


def test_partial_layout_resolves_only_matching_anchor_ids() -> None:
    page = parse_page(
        _anchored_page(anchors=(CrdtId(1, 16), CrdtId(1, 17))),
        page_id="partial-layout",
        text_anchor_layout=TextAnchorLayout(
            {CrdtIdentifier(1, 16): 12.0}, "partial native layout"
        ),
    )
    groups = {
        group.extra["anchor_id"]["value"]["text"]: group
        for group in page.groups
        if group.kind == "group"
    }

    assert groups["1:16"].local_transform.matrix[-2:] == (400.0, 246.0)
    assert groups["1:16"].local_transform.resolved is True
    assert groups["1:17"].local_transform.resolved is False
    assert "heuristic text anchor" in groups["1:17"].local_transform.evidence
    assert any(
        "Unverified group anchor 1:17" in warning
        for warning in page.diagnostics.warnings
    )
    assert not any(
        "Unverified group anchor 1:16" in warning
        for warning in page.diagnostics.warnings
    )


def test_caller_layout_does_not_resolve_unverified_anchor_types() -> None:
    page = parse_page(
        _anchored_page(anchor_type=1),
        page_id="unsupported-anchor-type",
        text_anchor_layout=TextAnchorLayout(
            {CrdtIdentifier(1, 17): 20.0}, "type-2-only native evidence"
        ),
    )

    group = next(group for group in page.groups if group.kind == "group")
    assert group.local_transform.resolved is False
    assert "anchor type 1" in group.local_transform.evidence
    assert any(
        "Unverified group anchor 1:17" in warning
        and "retained heuristic translation (400.0, 366.5)" in warning
        for warning in page.diagnostics.warnings
    )
    assert not any("used zero Y" in warning for warning in page.diagnostics.warnings)


def test_text_anchor_layout_is_immutable_and_validated() -> None:
    source = {CrdtIdentifier(1, 17): 20}
    layout = TextAnchorLayout(source, "caller measurement")
    source[CrdtIdentifier(1, 17)] = 99

    assert layout.offsets[CrdtIdentifier(1, 17)] == 20.0
    with pytest.raises(TypeError):
        layout.offsets[CrdtIdentifier(1, 17)] = 30.0  # type: ignore[index]
    with pytest.raises(ValueError, match="evidence"):
        TextAnchorLayout({}, "   ")
    with pytest.raises(ValueError, match="finite"):
        TextAnchorLayout({CrdtIdentifier(1, 17): float("nan")}, "bad offset")
    with pytest.raises(TypeError, match="CrdtIdentifier"):
        TextAnchorLayout({(1, 17): 20.0}, "bad key")  # type: ignore[dict-item]


def test_parsing_package_has_no_rendering_import() -> None:
    parsing_root = Path(__file__).parents[2] / "src" / "rm_redraw" / "parsing"
    imported_modules = set()
    for path in parsing_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

    assert not any("rendering" in module for module in imported_modules)
