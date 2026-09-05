from __future__ import annotations

import base64
import dataclasses
import enum
import json
from pathlib import Path
from typing import BinaryIO, TextIO
from uuid import UUID

from rmscene import (
    AuthorIdsBlock,
    CrdtSequence,
    MigrationInfoBlock,
    PageInfoBlock,
    SceneGroupItemBlock,
    SceneInfo,
    SceneItemBlock,
    SceneLineItemBlock,
    SceneTombstoneItemBlock,
    SceneTreeBlock,
    TreeNodeBlock,
    UnreadableBlock,
    read_blocks,
)
from rmscene.tagged_block_common import CrdtId, LwwValue

from .model import (
    BlockDiagnostic,
    CrdtIdentifier,
    EnumValue,
    MigrationMetadata,
    NormalizedGroup,
    NormalizedPage,
    NormalizedPoint,
    NormalizedStroke,
    NormalizedTombstone,
    PageDiagnostics,
    PageInfoMetadata,
    PageMetadata,
    ReplayOrder,
    ReplayStrategy,
    SceneOrder,
    VersionedValue,
)

type Source = str | Path | BinaryIO
ROOT_ID = CrdtId(0, 1)
IDENTITY_TRANSFORM = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _crdt(value: CrdtId) -> CrdtIdentifier:
    return CrdtIdentifier(value.part1, value.part2)


def _versioned(value: LwwValue) -> VersionedValue:
    normalized_value = _crdt(value.value) if isinstance(value.value, CrdtId) else value.value
    return VersionedValue(timestamp=_crdt(value.timestamp), value=normalized_value)


def _scene_order(block: SceneItemBlock, index: int) -> SceneOrder:
    item = block.item
    return SceneOrder(
        item_id=_crdt(item.item_id),
        left_id=_crdt(item.left_id),
        right_id=_crdt(item.right_id),
        deleted_length=item.deleted_length,
        block_index=index,
    )


def _enum_value(value: object) -> EnumValue:
    return EnumValue(code=int(value), name=getattr(value, "name", None))


def _layer_for(parent: CrdtId, parents: dict[CrdtId, CrdtId]) -> CrdtId:
    node = parent
    visited: set[CrdtId] = set()
    while node != ROOT_ID and node not in visited:
        visited.add(node)
        ancestor = parents.get(node, ROOT_ID)
        if ancestor == ROOT_ID:
            return node
        node = ancestor
    return parent


def _base64_or_none(value: bytes) -> str | None:
    if not value:
        return None
    return base64.b64encode(value).decode("ascii")


def _json_value(value: object) -> object:
    if isinstance(value, CrdtId):
        return {"part1": value.part1, "part2": value.part2, "text": f"{value.part1}:{value.part2}"}
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, enum.Enum):
        return {"code": int(value.value), "name": value.name}
    if isinstance(value, bytes):
        return {"base64": base64.b64encode(value).decode("ascii"), "length": len(value)}
    if isinstance(value, CrdtSequence):
        return [_json_value(item) for item in value.sequence_items()]
    if dataclasses.is_dataclass(value):
        return {
            field.name: _json_value(getattr(value, field.name))
            for field in dataclasses.fields(value)
            if field.name not in {"extra_data", "extra_value_data", "data", "info"}
        }
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _block_diagnostics(blocks: list[object]) -> PageDiagnostics:
    diagnostics: list[BlockDiagnostic] = []
    warnings: list[str] = []
    for index, block in enumerate(blocks):
        unreadable = isinstance(block, UnreadableBlock)
        extra_data = getattr(block, "extra_data", b"")
        extra_value_data = getattr(block, "extra_value_data", b"")
        error = block.error if unreadable else None
        raw_data = block.data if unreadable else b""
        if unreadable:
            warnings.append(f"Unreadable block {index} (type {block.get_block_type()}): {error}")
        if extra_data:
            warnings.append(f"Block {index} ({type(block).__name__}) has unparsed data")
        if extra_value_data:
            warnings.append(f"Block {index} ({type(block).__name__}) has unparsed value data")
        diagnostics.append(
            BlockDiagnostic(
                block_index=index,
                block_type=block.get_block_type(),
                block_name=type(block).__name__,
                unreadable=unreadable,
                error=error,
                raw_data_base64=_base64_or_none(raw_data),
                extra_data_base64=_base64_or_none(extra_data),
                extra_value_data_base64=_base64_or_none(extra_value_data),
                fields=_json_value(block),
            )
        )
    return PageDiagnostics(blocks=tuple(diagnostics), warnings=tuple(warnings))


def _parse_stream(
    stream: BinaryIO, page_id: str, replay_strategy: ReplayStrategy
) -> NormalizedPage:
    blocks = list(read_blocks(stream))
    scene_info = next((block for block in blocks if isinstance(block, SceneInfo)), None)
    author_ids: dict[int, str] = {}
    for block in blocks:
        if isinstance(block, AuthorIdsBlock):
            author_ids.update(
                {
                    author_id: str(author_uuid)
                    for author_id, author_uuid in block.author_uuids.items()
                }
            )
    migrations = tuple(
        MigrationMetadata(
            migration_id=_crdt(block.migration_id),
            is_device=block.is_device,
            unknown=block._unknown,
        )
        for block in blocks
        if isinstance(block, MigrationInfoBlock)
    )
    page_info_block = next(
        (block for block in reversed(blocks) if isinstance(block, PageInfoBlock)), None
    )
    page_info = (
        PageInfoMetadata(
            loads_count=page_info_block.loads_count,
            merges_count=page_info_block.merges_count,
            text_chars_count=page_info_block.text_chars_count,
            text_lines_count=page_info_block.text_lines_count,
            type_folio_use_count=page_info_block.type_folio_use_count,
        )
        if page_info_block is not None
        else None
    )
    metadata = PageMetadata(
        current_layer=_versioned(scene_info.current_layer) if scene_info is not None else None,
        background_visible=(
            _versioned(scene_info.background_visible)
            if scene_info is not None and scene_info.background_visible is not None
            else None
        ),
        root_document_visible=(
            _versioned(scene_info.root_document_visible)
            if scene_info is not None and scene_info.root_document_visible is not None
            else None
        ),
        authors=author_ids,
        migrations=migrations,
        page_info=page_info,
    )

    tree_blocks = {
        block.tree_id: block for block in blocks if isinstance(block, SceneTreeBlock)
    }
    node_details = {
        block.group.node_id: block.group for block in blocks if isinstance(block, TreeNodeBlock)
    }
    group_items = {
        block.item.value: (index, block)
        for index, block in enumerate(blocks)
        if isinstance(block, SceneGroupItemBlock) and block.item.value is not None
    }
    parents = {node_id: block.parent_id for node_id, block in tree_blocks.items()}
    item_blocks_by_parent: dict[CrdtId, list[SceneItemBlock]] = {}
    for block in blocks:
        if isinstance(block, SceneItemBlock):
            item_blocks_by_parent.setdefault(block.parent_id, []).append(block)

    groups: list[NormalizedGroup] = []
    for node_id, tree_block in tree_blocks.items():
        group = node_details.get(node_id)
        positioned = group_items.get(node_id)
        if group is None or positioned is None:
            continue
        block_index, item_block = positioned
        layer_id = _layer_for(node_id, parents)
        groups.append(
            NormalizedGroup(
                node_id=_crdt(node_id),
                source_node_id=_crdt(tree_block.node_id),
                parent_id=_crdt(tree_block.parent_id),
                layer_id=_crdt(layer_id),
                kind="layer" if tree_block.parent_id == ROOT_ID else "group",
                label=_versioned(group.label),
                visible=_versioned(group.visible),
                scene_order=_scene_order(item_block, block_index),
                extra={
                    "is_update": tree_block.is_update,
                    "anchor_id": _json_value(group.anchor_id),
                    "anchor_type": _json_value(group.anchor_type),
                    "anchor_threshold": _json_value(group.anchor_threshold),
                    "anchor_origin_x": _json_value(group.anchor_origin_x),
                },
            )
        )
    ordered_group_ids: list[CrdtId] = []
    visited_groups: set[CrdtId] = set()

    def append_scene_groups(parent_id: CrdtId) -> None:
        item_blocks = item_blocks_by_parent.get(parent_id, [])
        sequence = CrdtSequence(block.item for block in item_blocks)
        blocks_by_id = {block.item.item_id: block for block in item_blocks}
        for item_id in sequence:
            item_block = blocks_by_id[item_id]
            if not isinstance(item_block, SceneGroupItemBlock):
                continue
            group_id = item_block.item.value
            if group_id is None or group_id in visited_groups:
                continue
            visited_groups.add(group_id)
            ordered_group_ids.append(group_id)
            append_scene_groups(group_id)

    append_scene_groups(ROOT_ID)
    group_rank = {group_id: rank for rank, group_id in enumerate(ordered_group_ids)}
    groups.sort(
        key=lambda group: (
            group_rank.get(CrdtId(*group.node_id.as_tuple()), len(group_rank)),
            group.scene_order.block_index,
        )
    )

    strokes: list[NormalizedStroke] = []
    for index, block in enumerate(blocks):
        if not isinstance(block, SceneLineItemBlock) or block.item.value is None:
            continue
        line = block.item.value
        strokes.append(
            NormalizedStroke(
                stroke_id=_crdt(block.item.item_id),
                parent_id=_crdt(block.parent_id),
                layer_id=_crdt(_layer_for(block.parent_id, parents)),
                scene_order=_scene_order(block, index),
                move_id=_crdt(line.move_id) if line.move_id is not None else None,
                tool=_enum_value(line.tool),
                color=_enum_value(line.color),
                color_rgba=line.color_rgba,
                thickness_scale=line.thickness_scale,
                starting_length=line.starting_length,
                points=tuple(
                    NormalizedPoint(
                        x=point.x,
                        y=point.y,
                        pressure=point.pressure,
                        speed=point.speed,
                        direction=point.direction,
                        width=point.width,
                    )
                    for point in line.points
                ),
            )
        )

    tombstones = tuple(
        NormalizedTombstone(
            tombstone_id=_crdt(block.item.item_id),
            parent_id=_crdt(block.parent_id),
            scene_order=_scene_order(block, index),
        )
        for index, block in enumerate(blocks)
        if isinstance(block, SceneTombstoneItemBlock)
    )

    compositing_ids: list[CrdtIdentifier] = []
    composited_groups: set[CrdtId] = set()
    composited_strokes: set[CrdtId] = set()

    def append_scene_strokes(parent_id: CrdtId) -> None:
        if parent_id in composited_groups:
            return
        composited_groups.add(parent_id)
        item_blocks = item_blocks_by_parent.get(parent_id, [])
        sequence = CrdtSequence(block.item for block in item_blocks)
        blocks_by_id = {block.item.item_id: block for block in item_blocks}
        for item_id in sequence:
            item_block = blocks_by_id[item_id]
            if isinstance(item_block, SceneLineItemBlock):
                if item_block.item.value is not None and item_id not in composited_strokes:
                    composited_strokes.add(item_id)
                    compositing_ids.append(_crdt(item_id))
            elif item_block.item.value is not None:
                if isinstance(item_block, SceneGroupItemBlock):
                    append_scene_strokes(item_block.item.value)

    append_scene_strokes(ROOT_ID)
    compositing_order = tuple(compositing_ids)
    if replay_strategy == "scene-order":
        replay_order = ReplayOrder(
            strategy="scene-order",
            stroke_ids=compositing_order,
            evidence="Deterministic scene compositing order fallback; drawing time is unverified.",
        )
    else:
        replay_order = ReplayOrder(
            strategy="crdt-order",
            stroke_ids=tuple(
                sorted(
                    (stroke.stroke_id for stroke in strokes),
                    key=lambda item_id: (item_id.part2, item_id.part1),
                )
            ),
            evidence=(
                "Deterministic ordering by CRDT counter then author identifier; "
                "drawing time is unverified."
            ),
        )

    return NormalizedPage(
        page_id=page_id,
        paper_size=scene_info.paper_size if scene_info is not None else None,
        source_to_page_transform=IDENTITY_TRANSFORM,
        groups=tuple(groups),
        strokes=tuple(strokes),
        tombstones=tombstones,
        compositing_order=compositing_order,
        replay_order=replay_order,
        metadata=metadata,
        diagnostics=_block_diagnostics(blocks),
    )


def parse_page(
    source: Source,
    *,
    page_id: str | None = None,
    replay_strategy: ReplayStrategy = "crdt-order",
) -> NormalizedPage:
    if replay_strategy not in ("crdt-order", "scene-order"):
        raise ValueError(f"unknown replay strategy: {replay_strategy}")
    if hasattr(source, "read"):
        if page_id is None:
            raise ValueError("page_id is required when parsing a binary stream")
        return _parse_stream(source, page_id, replay_strategy)

    path = Path(source)
    resolved_page_id = page_id if page_id is not None else path.stem
    with path.open("rb") as stream:
        return _parse_stream(stream, resolved_page_id, replay_strategy)


def dump_page_json(
    page: NormalizedPage,
    destination: str | Path | TextIO | None = None,
    *,
    indent: int = 2,
) -> str:
    payload = {"schema_version": 1, "page": _json_value(page)}
    encoded = json.dumps(payload, indent=indent, sort_keys=True, ensure_ascii=False) + "\n"
    if destination is None:
        return encoded
    if hasattr(destination, "write"):
        destination.write(encoded)
    else:
        Path(destination).write_text(encoded, encoding="utf-8", newline="\n")
    return encoded
