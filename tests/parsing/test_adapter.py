from __future__ import annotations

import json
from io import BytesIO
from uuid import UUID

from rmscene import (
    AuthorIdsBlock,
    CrdtId,
    CrdtSequenceItem,
    LwwValue,
    MigrationInfoBlock,
    PageInfoBlock,
    SceneGroupItemBlock,
    SceneInfo,
    SceneLineItemBlock,
    SceneTombstoneItemBlock,
    SceneTreeBlock,
    TreeNodeBlock,
    UnreadableBlock,
    simple_text_document,
    write_blocks,
)
from rmscene import scene_items as si
from rmscene.tagged_block_reader import MainBlockInfo

from rm_redraw.parsing import dump_page_json, parse_page

END = CrdtId(0, 0)
ROOT = CrdtId(0, 1)


def _synthetic_page() -> BytesIO:
    layer_id = CrdtId(7, 100)
    layer_item_id = CrdtId(7, 101)
    stroke_item_id = CrdtId(7, 102)
    blocks = [
        SceneInfo(
            current_layer=LwwValue(CrdtId(7, 90), layer_id),
            background_visible=LwwValue(CrdtId(7, 91), True),
            root_document_visible=LwwValue(CrdtId(7, 92), False),
            paper_size=(1620, 2160),
        ),
        SceneTreeBlock(
            tree_id=layer_id,
            node_id=layer_id,
            is_update=False,
            parent_id=ROOT,
        ),
        TreeNodeBlock(
            si.Group(
                node_id=layer_id,
                label=LwwValue(CrdtId(7, 93), "Ink"),
                visible=LwwValue(CrdtId(7, 94), True),
            )
        ),
        SceneGroupItemBlock(
            parent_id=ROOT,
            item=CrdtSequenceItem(layer_item_id, END, END, 0, layer_id),
        ),
        SceneLineItemBlock(
            parent_id=layer_id,
            item=CrdtSequenceItem(
                stroke_item_id,
                END,
                END,
                0,
                si.Line(
                    color=si.PenColor.BLUE,
                    tool=si.Pen.BALLPOINT_2,
                    points=[si.Point(10.5, 20.25, 300, 64, 12, 190)],
                    thickness_scale=1.75,
                    starting_length=4.5,
                    move_id=CrdtId(7, 80),
                    color_rgba=(1, 2, 3, 4),
                ),
            ),
        ),
    ]
    data = BytesIO()
    write_blocks(data, blocks, options={"version": "3.27.3"})
    data.seek(0)
    return data


def test_parse_page_retains_complete_stroke_metadata() -> None:
    page = parse_page(_synthetic_page(), page_id="page-1")

    assert page.page_id == "page-1"
    assert page.paper_size == (1620, 2160)
    assert page.source_to_page_transform is None

    assert len(page.groups) == 1
    layer = page.groups[0]
    assert layer.node_id.as_tuple() == (7, 100)
    assert layer.parent_id.as_tuple() == (0, 1)
    assert layer.layer_id == layer.node_id
    assert layer.kind == "layer"
    assert layer.label.value == "Ink"
    assert layer.label.timestamp.as_tuple() == (7, 93)
    assert layer.scene_order.item_id.as_tuple() == (7, 101)
    assert layer.effective_transform.resolved is True
    assert layer.effective_transform.matrix == (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

    assert len(page.strokes) == 1
    stroke = page.strokes[0]
    assert stroke.stroke_id.as_tuple() == (7, 102)
    assert stroke.parent_id == layer.node_id
    assert stroke.layer_id == layer.node_id
    assert stroke.scene_order.left_id.as_tuple() == (0, 0)
    assert stroke.scene_order.right_id.as_tuple() == (0, 0)
    assert stroke.scene_order.deleted_length == 0
    assert stroke.move_id.as_tuple() == (7, 80)
    assert (stroke.tool.code, stroke.tool.name) == (15, "BALLPOINT_2")
    assert (stroke.color.code, stroke.color.name) == (6, "BLUE")
    assert stroke.color_rgba == (1, 2, 3, 4)
    assert stroke.thickness_scale == 1.75
    assert stroke.starting_length == 4.5
    assert stroke.points[0].x == 10.5
    assert stroke.points[0].y == 20.25
    assert stroke.points[0].pressure == 190
    assert stroke.points[0].speed == 300
    assert stroke.points[0].direction == 64
    assert stroke.points[0].width == 12
    assert stroke.points[0].extra == {}


def _line_block(
    *, item_id: CrdtId, left_id: CrdtId, right_id: CrdtId, parent_id: CrdtId
) -> SceneLineItemBlock:
    return SceneLineItemBlock(
        parent_id=parent_id,
        item=CrdtSequenceItem(
            item_id,
            left_id,
            right_id,
            0,
            si.Line(
                color=si.PenColor.BLACK,
                tool=si.Pen.FINELINER_2,
                points=[si.Point(float(item_id.part2), 1.0, 1, 2, 3, 4)],
                thickness_scale=1.0,
                starting_length=0.0,
            ),
        ),
    )


def _out_of_order_page() -> BytesIO:
    layer_id = CrdtId(9, 50)
    scene_first = CrdtId(9, 200)
    scene_second = CrdtId(9, 100)
    blocks = [
        SceneTreeBlock(layer_id, layer_id, False, ROOT),
        TreeNodeBlock(
            si.Group(
                node_id=layer_id,
                label=LwwValue(CrdtId(9, 51), "Layer"),
                visible=LwwValue(CrdtId(9, 52), True),
            )
        ),
        SceneGroupItemBlock(
            parent_id=ROOT,
            item=CrdtSequenceItem(CrdtId(9, 53), END, END, 0, layer_id),
        ),
        _line_block(
            item_id=scene_second,
            left_id=scene_first,
            right_id=END,
            parent_id=layer_id,
        ),
        _line_block(
            item_id=scene_first,
            left_id=END,
            right_id=scene_second,
            parent_id=layer_id,
        ),
    ]
    data = BytesIO()
    write_blocks(data, blocks, options={"version": "3.27.3"})
    data.seek(0)
    return data


def test_compositing_and_fallback_replay_orders_are_distinct_and_labeled() -> None:
    crdt_page = parse_page(_out_of_order_page(), page_id="page-order")
    scene_page = parse_page(
        _out_of_order_page(), page_id="page-order", replay_strategy="scene-order"
    )

    assert [item.as_tuple() for item in crdt_page.compositing_order] == [
        (9, 200),
        (9, 100),
    ]
    assert crdt_page.replay_order.strategy == "crdt-order"
    assert [item.as_tuple() for item in crdt_page.replay_order.stroke_ids] == [
        (9, 100),
        (9, 200),
    ]
    assert "chronolog" not in crdt_page.replay_order.evidence.lower()

    assert scene_page.replay_order.strategy == "scene-order"
    assert scene_page.replay_order.stroke_ids == scene_page.compositing_order
    assert "chronolog" not in scene_page.replay_order.evidence.lower()


def test_groups_follow_scene_links_instead_of_serialized_block_order() -> None:
    first_layer = CrdtId(12, 10)
    second_layer = CrdtId(12, 20)
    first_item = CrdtId(12, 100)
    second_item = CrdtId(12, 50)
    blocks = [
        SceneTreeBlock(second_layer, second_layer, False, ROOT),
        SceneTreeBlock(first_layer, first_layer, False, ROOT),
        TreeNodeBlock(
            si.Group(
                second_layer,
                label=LwwValue(CrdtId(12, 21), "Second"),
                visible=LwwValue(CrdtId(12, 22), True),
            )
        ),
        TreeNodeBlock(
            si.Group(
                first_layer,
                label=LwwValue(CrdtId(12, 11), "First"),
                visible=LwwValue(CrdtId(12, 12), True),
            )
        ),
        SceneGroupItemBlock(
            ROOT,
            CrdtSequenceItem(second_item, first_item, END, 0, second_layer),
        ),
        SceneGroupItemBlock(
            ROOT,
            CrdtSequenceItem(first_item, END, second_item, 0, first_layer),
        ),
    ]
    data = BytesIO()
    write_blocks(data, blocks, options={"version": "3.27.3"})
    data.seek(0)

    page = parse_page(data, page_id="group-order")

    assert [group.label.value for group in page.groups] == ["First", "Second"]


def test_compositing_order_does_not_repeat_reinserted_group_contents() -> None:
    layer_id = CrdtId(13, 10)
    stroke_id = CrdtId(13, 20)
    blocks = [
        SceneTreeBlock(layer_id, layer_id, False, ROOT),
        TreeNodeBlock(
            si.Group(
                layer_id,
                label=LwwValue(CrdtId(13, 11), "Moved layer"),
                visible=LwwValue(CrdtId(13, 12), True),
            )
        ),
        SceneGroupItemBlock(
            ROOT,
            CrdtSequenceItem(CrdtId(13, 13), END, CrdtId(13, 14), 0, layer_id),
        ),
        SceneGroupItemBlock(
            ROOT,
            CrdtSequenceItem(CrdtId(13, 14), CrdtId(13, 13), END, 0, layer_id),
        ),
        _line_block(item_id=stroke_id, left_id=END, right_id=END, parent_id=layer_id),
    ]
    data = BytesIO()
    write_blocks(data, blocks, options={"version": "3.27.3"})
    data.seek(0)

    page = parse_page(data, page_id="reinserted-group")

    assert [item.as_tuple() for item in page.compositing_order] == [(13, 20)]


def test_anchored_group_translation_is_exposed_without_changing_raw_points() -> None:
    anchored_group_id = CrdtId(14, 100)
    stroke_id = CrdtId(14, 110)
    blocks = [
        *simple_text_document("\n\n"),
        SceneTreeBlock(anchored_group_id, anchored_group_id, False, CrdtId(0, 11)),
        TreeNodeBlock(
            si.Group(
                anchored_group_id,
                label=LwwValue(CrdtId(14, 101), "Anchored"),
                visible=LwwValue(CrdtId(14, 102), True),
                anchor_id=LwwValue(CrdtId(14, 103), CrdtId(1, 17)),
                anchor_type=LwwValue(CrdtId(14, 104), 2),
                anchor_threshold=LwwValue(CrdtId(14, 105), 35.75),
                anchor_origin_x=LwwValue(CrdtId(14, 106), 10.0),
            )
        ),
        SceneGroupItemBlock(
            CrdtId(0, 11),
            CrdtSequenceItem(CrdtId(14, 107), END, END, 0, anchored_group_id),
        ),
        _line_block(
            item_id=stroke_id,
            left_id=END,
            right_id=END,
            parent_id=anchored_group_id,
        ),
    ]
    data = BytesIO()
    write_blocks(data, blocks, options={"version": "3.27.3"})
    data.seek(0)

    page = parse_page(data, page_id="anchored")

    group = next(group for group in page.groups if group.node_id.as_tuple() == (14, 100))
    stroke = next(stroke for stroke in page.strokes if stroke.stroke_id.as_tuple() == (14, 110))
    assert group.local_transform.matrix == (1.0, 0.0, 0.0, 1.0, 10.0, 366.5)
    assert group.effective_transform == group.local_transform
    assert group.effective_transform.resolved is False
    assert "heuristic text anchor" in group.effective_transform.evidence
    assert "paired native PDF fixture" in group.effective_transform.evidence
    assert "full text layout semantics are unresolved" in group.effective_transform.evidence
    assert stroke.effective_transform == group.effective_transform
    assert (stroke.points[0].x, stroke.points[0].y) == (110.0, 1.0)
    assert any(
        "Unverified group anchor 1:17" in warning
        and "retained heuristic translation (10.0, 366.5)" in warning
        and "full text layout semantics are unresolved" in warning
        for warning in page.diagnostics.warnings
    )


def test_plain_text_anchor_positions_use_native_pdf_calibrated_origin_and_spacing() -> None:
    first_group_id = CrdtId(17, 100)
    second_group_id = CrdtId(17, 200)

    def anchored_group(node_id: CrdtId, anchor_id: CrdtId) -> si.Group:
        return si.Group(
            node_id,
            label=LwwValue(CrdtId(node_id.part1, node_id.part2 + 1), "Anchored"),
            visible=LwwValue(CrdtId(node_id.part1, node_id.part2 + 2), True),
            anchor_id=LwwValue(CrdtId(node_id.part1, node_id.part2 + 3), anchor_id),
            anchor_type=LwwValue(CrdtId(node_id.part1, node_id.part2 + 4), 2),
            anchor_threshold=LwwValue(CrdtId(node_id.part1, node_id.part2 + 5), 35.75),
            anchor_origin_x=LwwValue(CrdtId(node_id.part1, node_id.part2 + 6), -464.0),
        )

    blocks = [
        *simple_text_document("\n\n"),
        SceneTreeBlock(first_group_id, first_group_id, False, CrdtId(0, 11)),
        TreeNodeBlock(anchored_group(first_group_id, CrdtId(1, 16))),
        SceneGroupItemBlock(
            CrdtId(0, 11),
            CrdtSequenceItem(CrdtId(17, 110), END, END, 0, first_group_id),
        ),
        SceneTreeBlock(second_group_id, second_group_id, False, CrdtId(0, 11)),
        TreeNodeBlock(anchored_group(second_group_id, CrdtId(1, 17))),
        SceneGroupItemBlock(
            CrdtId(0, 11),
            CrdtSequenceItem(CrdtId(17, 210), END, END, 0, second_group_id),
        ),
    ]
    data = BytesIO()
    write_blocks(data, blocks, options={"version": "3.27.3"})
    data.seek(0)

    page = parse_page(data, page_id="native-calibrated-anchors")

    translations = {
        group.node_id.as_tuple(): group.local_transform.matrix[-2:]
        for group in page.groups
        if group.node_id.as_tuple() in {(17, 100), (17, 200)}
    }
    assert translations == {
        (17, 100): (-464.0, 297.0),
        (17, 200): (-464.0, 366.5),
    }


def test_special_page_anchors_without_root_text_remain_resolved() -> None:
    top_group_id = CrdtId(18, 100)
    bottom_group_id = CrdtId(18, 200)

    def anchored_group(node_id: CrdtId, anchor_id: CrdtId, origin_x: float) -> si.Group:
        return si.Group(
            node_id,
            label=LwwValue(CrdtId(node_id.part1, node_id.part2 + 1), "Anchored"),
            visible=LwwValue(CrdtId(node_id.part1, node_id.part2 + 2), True),
            anchor_id=LwwValue(CrdtId(node_id.part1, node_id.part2 + 3), anchor_id),
            anchor_type=LwwValue(CrdtId(node_id.part1, node_id.part2 + 4), 2),
            anchor_threshold=LwwValue(CrdtId(node_id.part1, node_id.part2 + 5), 35.75),
            anchor_origin_x=LwwValue(CrdtId(node_id.part1, node_id.part2 + 6), origin_x),
        )

    blocks = [
        SceneInfo(
            current_layer=LwwValue(CrdtId(18, 1), top_group_id),
            background_visible=LwwValue(CrdtId(18, 2), True),
            root_document_visible=LwwValue(CrdtId(18, 3), True),
            paper_size=(1404, 1872),
        ),
        SceneTreeBlock(top_group_id, top_group_id, False, ROOT),
        TreeNodeBlock(
            anchored_group(top_group_id, CrdtId(0, 281474976710654), 4.0)
        ),
        SceneGroupItemBlock(
            ROOT, CrdtSequenceItem(CrdtId(18, 110), END, END, 0, top_group_id)
        ),
        SceneTreeBlock(bottom_group_id, bottom_group_id, False, ROOT),
        TreeNodeBlock(
            anchored_group(bottom_group_id, CrdtId(0, 281474976710655), 8.0)
        ),
        SceneGroupItemBlock(
            ROOT, CrdtSequenceItem(CrdtId(18, 210), END, END, 0, bottom_group_id)
        ),
    ]
    data = BytesIO()
    write_blocks(data, blocks, options={"version": "3.27.3"})
    data.seek(0)

    page = parse_page(data, page_id="special-page-anchors")

    transforms = {
        group.node_id.as_tuple(): group.local_transform for group in page.groups
    }
    assert transforms[(18, 100)].matrix[-2:] == (4.0, 0.0)
    assert transforms[(18, 200)].matrix[-2:] == (8.0, 1872.0)
    assert transforms[(18, 100)].resolved is True
    assert transforms[(18, 200)].resolved is True
    assert "special page anchors without root text" in transforms[(18, 100)].evidence
    assert not any("group anchor" in warning for warning in page.diagnostics.warnings)


def test_nested_group_translations_compose_parent_before_child() -> None:
    parent_id = CrdtId(16, 100)
    child_id = CrdtId(16, 200)
    stroke_id = CrdtId(16, 300)

    def anchored_group(node_id: CrdtId, origin_x: float) -> si.Group:
        return si.Group(
            node_id,
            label=LwwValue(CrdtId(node_id.part1, node_id.part2 + 1), "Anchored"),
            visible=LwwValue(CrdtId(node_id.part1, node_id.part2 + 2), True),
            anchor_id=LwwValue(CrdtId(node_id.part1, node_id.part2 + 3), CrdtId(1, 17)),
            anchor_type=LwwValue(CrdtId(node_id.part1, node_id.part2 + 4), 2),
            anchor_threshold=LwwValue(CrdtId(node_id.part1, node_id.part2 + 5), 35.75),
            anchor_origin_x=LwwValue(CrdtId(node_id.part1, node_id.part2 + 6), origin_x),
        )

    blocks = [
        *simple_text_document("\n\n"),
        SceneTreeBlock(parent_id, parent_id, False, ROOT),
        TreeNodeBlock(anchored_group(parent_id, 10.0)),
        SceneGroupItemBlock(
            ROOT, CrdtSequenceItem(CrdtId(16, 110), END, END, 0, parent_id)
        ),
        SceneTreeBlock(child_id, child_id, False, parent_id),
        TreeNodeBlock(anchored_group(child_id, 5.0)),
        SceneGroupItemBlock(
            parent_id, CrdtSequenceItem(CrdtId(16, 210), END, END, 0, child_id)
        ),
        _line_block(
            item_id=stroke_id,
            left_id=END,
            right_id=END,
            parent_id=child_id,
        ),
    ]
    data = BytesIO()
    write_blocks(data, blocks, options={"version": "3.27.3"})
    data.seek(0)

    page = parse_page(data, page_id="nested-anchors")

    child = next(group for group in page.groups if group.node_id.as_tuple() == (16, 200))
    stroke = next(stroke for stroke in page.strokes if stroke.stroke_id.as_tuple() == (16, 300))
    assert child.local_transform.matrix[-2:] == (5.0, 366.5)
    assert child.effective_transform.matrix[-2:] == (15.0, 733.0)
    assert stroke.effective_transform == child.effective_transform


def test_unknown_group_anchor_is_retained_and_reported_as_unresolved() -> None:
    layer_id = CrdtId(15, 10)
    blocks = [
        SceneTreeBlock(layer_id, layer_id, False, ROOT),
        TreeNodeBlock(
            si.Group(
                layer_id,
                label=LwwValue(CrdtId(15, 11), "Unknown anchor"),
                visible=LwwValue(CrdtId(15, 12), True),
                anchor_id=LwwValue(CrdtId(15, 13), CrdtId(15, 999)),
                anchor_type=LwwValue(CrdtId(15, 14), 2),
                anchor_threshold=LwwValue(CrdtId(15, 15), 35.75),
                anchor_origin_x=LwwValue(CrdtId(15, 16), -20.0),
            )
        ),
        SceneGroupItemBlock(
            ROOT,
            CrdtSequenceItem(CrdtId(15, 17), END, END, 0, layer_id),
        ),
    ]
    data = BytesIO()
    write_blocks(data, blocks, options={"version": "3.27.3"})
    data.seek(0)

    page = parse_page(data, page_id="unknown-anchor")

    assert page.groups[0].effective_transform.resolved is False
    assert page.groups[0].effective_transform.anchor_ids[0].as_tuple() == (15, 999)
    assert page.groups[0].effective_transform.matrix[-2:] == (-20.0, 0.0)
    assert any("Unresolved group anchor 15:999" in warning for warning in page.diagnostics.warnings)


def _diagnostic_page() -> BytesIO:
    layer_id = CrdtId(11, 10)
    stroke_id = CrdtId(11, 20)
    blocks = [
        AuthorIdsBlock({11: UUID("12345678-1234-5678-1234-567812345678")}),
        MigrationInfoBlock(CrdtId(11, 1), True, True),
        PageInfoBlock(3, 2, 1, 1, 4),
        SceneInfo(
            current_layer=LwwValue(CrdtId(11, 2), layer_id),
            background_visible=LwwValue(CrdtId(11, 3), False),
            root_document_visible=LwwValue(CrdtId(11, 4), True),
            paper_size=(1404, 1872),
            extra_data=b"\xaa",
        ),
        SceneTreeBlock(layer_id, layer_id, False, ROOT),
        TreeNodeBlock(
            si.Group(
                node_id=layer_id,
                label=LwwValue(CrdtId(11, 11), "Layer"),
                visible=LwwValue(CrdtId(11, 12), True),
            )
        ),
        SceneGroupItemBlock(
            parent_id=ROOT,
            item=CrdtSequenceItem(CrdtId(11, 13), END, END, 0, layer_id),
        ),
        SceneLineItemBlock(
            parent_id=layer_id,
            item=CrdtSequenceItem(
                stroke_id,
                END,
                END,
                0,
                si.Line(
                    color=si.PenColor.BLACK,
                    tool=si.Pen.PENCIL_2,
                    points=[si.Point(1.0, 2.0, 3, 4, 5, 6)],
                    thickness_scale=1.0,
                    starting_length=0.5,
                ),
            ),
            extra_value_data=b"\xbb\xcc",
        ),
        SceneTombstoneItemBlock(
            parent_id=layer_id,
            item=CrdtSequenceItem(CrdtId(11, 21), stroke_id, END, 1, None),
        ),
        UnreadableBlock(
            "synthetic unknown block",
            b"\xde\xad\xbe\xef",
            MainBlockInfo(0, 4, block_type=0x7F, min_version=1, current_version=1),
        ),
    ]
    data = BytesIO()
    write_blocks(data, blocks, options={"version": "3.27.3"})
    data.seek(0)
    return data


def test_diagnostics_retain_tombstones_unknown_data_and_page_metadata() -> None:
    page = parse_page(_diagnostic_page(), page_id="page-diagnostic")

    assert page.metadata.current_layer.value.as_tuple() == (11, 10)
    assert page.metadata.background_visible.value is False
    assert page.metadata.root_document_visible.value is True
    assert page.metadata.authors == {
        11: "12345678-1234-5678-1234-567812345678"
    }
    assert page.metadata.migrations[0].migration_id.as_tuple() == (11, 1)
    assert page.metadata.migrations[0].is_device is True
    assert page.metadata.migrations[0].unknown is True
    assert page.metadata.page_info.loads_count == 3
    assert page.metadata.page_info.type_folio_use_count == 4

    assert len(page.tombstones) == 1
    tombstone = page.tombstones[0]
    assert tombstone.tombstone_id.as_tuple() == (11, 21)
    assert tombstone.parent_id.as_tuple() == (11, 10)
    assert tombstone.scene_order.left_id.as_tuple() == (11, 20)
    assert tombstone.scene_order.right_id.as_tuple() == (0, 0)
    assert tombstone.scene_order.deleted_length == 1

    extras = [block for block in page.diagnostics.blocks if block.extra_data_base64]
    assert extras[0].extra_data_base64 == "qg=="
    value_extras = [
        block for block in page.diagnostics.blocks if block.extra_value_data_base64
    ]
    assert value_extras[0].extra_value_data_base64 == "u8w="
    unreadable = [block for block in page.diagnostics.blocks if block.unreadable]
    assert len(unreadable) == 1
    assert unreadable[0].block_type == 0x7F
    assert unreadable[0].raw_data_base64 == "3q2+7w=="

    encoded = dump_page_json(page)
    assert encoded == dump_page_json(page)
    diagnostic = json.loads(encoded)
    assert diagnostic["schema_version"] == 1
    assert diagnostic["page"]["page_id"] == "page-diagnostic"
    assert diagnostic["page"]["strokes"][0]["points"][0] == {
        "direction": 4,
        "extra": {},
        "pressure": 6,
        "speed": 3,
        "width": 5,
        "x": 1.0,
        "y": 2.0,
    }


def test_diagnostic_command_writes_readable_json(tmp_path) -> None:
    from rm_redraw.parsing.__main__ import main

    source = tmp_path / "source.rm"
    destination = tmp_path / "diagnostic.json"
    source.write_bytes(_diagnostic_page().getvalue())

    result = main(
        [
            str(source),
            "--page-id",
            "page-from-command",
            "--output",
            str(destination),
            "--replay-strategy",
            "scene-order",
        ]
    )

    assert result == 0
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["page"]["page_id"] == "page-from-command"
    assert payload["page"]["replay_order"]["strategy"] == "scene-order"
