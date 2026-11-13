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
    RootTextBlock,
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
from rmscene.text import TextDocument

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
    TextAnchorLayout,
    TransformResolution,
    VersionedValue,
)

type Source = str | Path | BinaryIO
ROOT_ID = CrdtId(0, 1)
IDENTITY_TRANSFORM = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
_SPECIAL_TOP_ANCHOR = CrdtId(0, 281474976710654)
_SPECIAL_BOTTOM_ANCHOR = CrdtId(0, 281474976710655)
# Calibrated against all five pages of paired native-PDF fixture
# (initial five-page natural anchor study). Unanchored ink remains at Y=0;
# anchored plain-paragraph groups resolve at pos_y + 63 + index * 69.5.
_TEXT_TOP_OFFSET = 63.0
_LINE_HEIGHT_BY_STYLE = {
    0: 70.0,
    1: 69.5,
    2: 150.0,
    3: 70.0,
    4: 35.0,
    5: 35.0,
    6: 35.0,
    7: 35.0,
}


@dataclasses.dataclass(frozen=True)
class _AnchorPosition:
    y: float
    resolved: bool
    evidence: str


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


def _identity_resolution(evidence: str) -> TransformResolution:
    return TransformResolution(IDENTITY_TRANSFORM, True, evidence)


def _anchor_positions(
    root_text_block: RootTextBlock | None,
    paper_size: tuple[int, int] | None,
) -> dict[CrdtId, _AnchorPosition]:
    if root_text_block is None:
        evidence = "special page anchors without root text"
        positions = {_SPECIAL_TOP_ANCHOR: _AnchorPosition(0.0, True, evidence)}
        if paper_size is not None:
            positions[_SPECIAL_BOTTOM_ANCHOR] = _AnchorPosition(
                float(paper_size[1]), True, evidence
            )
        return positions

    text = root_text_block.value
    document = TextDocument.from_scene_item(text)
    y_position = float(text.pos_y) + _TEXT_TOP_OFFSET
    top_of_text = y_position
    heuristic_evidence = (
        "root text anchor positions calibrated against the five-page paired native PDF "
        "fixture (initial natural anchor study; heuristic, not a general text layout)"
    )
    positions: dict[CrdtId, _AnchorPosition] = {}
    for paragraph in document.contents:
        position = _AnchorPosition(y_position, False, heuristic_evidence)
        positions[paragraph.start_id] = position
        for span in paragraph.contents:
            for character_id in span.i:
                positions[character_id] = position
        style_code = int(paragraph.style.value)
        y_position += _LINE_HEIGHT_BY_STYLE.get(style_code, 70.0)
    positions[_SPECIAL_TOP_ANCHOR] = _AnchorPosition(
        top_of_text, False, heuristic_evidence
    )
    positions[_SPECIAL_BOTTOM_ANCHOR] = _AnchorPosition(
        y_position, False, heuristic_evidence
    )
    return positions


def _local_group_transform(
    group: object,
    anchor_positions: dict[CrdtId, _AnchorPosition],
    root_text_pos_y: float | None,
    text_anchor_layout: TextAnchorLayout | None,
) -> TransformResolution:
    anchor = group.anchor_id
    if anchor is None:
        return _identity_resolution("Group has no anchor; identity translation.")

    anchor_id = anchor.value
    origin_x = float(group.anchor_origin_x.value) if group.anchor_origin_x is not None else 0.0
    anchor_type = int(group.anchor_type.value) if group.anchor_type is not None else None
    supplied_offset = (
        text_anchor_layout.offsets.get(_crdt(anchor_id))
        if text_anchor_layout is not None and root_text_pos_y is not None
        else None
    )
    if supplied_offset is not None and anchor_type == 2:
        return TransformResolution(
            matrix=(
                1.0,
                0.0,
                0.0,
                1.0,
                origin_x,
                root_text_pos_y + supplied_offset,
            ),
            resolved=True,
            evidence=(
                f"Resolved text anchor {anchor_id} from caller-supplied text anchor layout: "
                f"{text_anchor_layout.evidence}."
            ),
            anchor_ids=(_crdt(anchor_id),),
        )
    anchor_position = anchor_positions.get(anchor_id)
    if anchor_position is None:
        return TransformResolution(
            matrix=(1.0, 0.0, 0.0, 1.0, origin_x, 0.0),
            resolved=False,
            evidence=f"Unresolved text anchor {anchor_id}; retained X origin and used zero Y.",
            anchor_ids=(_crdt(anchor_id),),
        )
    if supplied_offset is not None:
        evidence = (
            f"Unverified anchor type {anchor_type} for text anchor {anchor_id}; "
            "caller-supplied type-2 layout evidence was not applied."
        )
    elif anchor_position.resolved:
        evidence = f"Resolved text anchor {anchor_id} from {anchor_position.evidence}."
    else:
        evidence = (
            f"Unverified heuristic text anchor {anchor_id} from {anchor_position.evidence}; "
            "retained calibrated matrix for diagnostics, but full text layout semantics "
            "are unresolved."
        )
    return TransformResolution(
        matrix=(1.0, 0.0, 0.0, 1.0, origin_x, anchor_position.y),
        resolved=anchor_position.resolved,
        evidence=evidence,
        anchor_ids=(_crdt(anchor_id),),
    )


def _compose_transforms(
    parent: TransformResolution, local: TransformResolution
) -> TransformResolution:
    if parent.matrix == IDENTITY_TRANSFORM and parent.resolved:
        return local
    pa, pb, pc, pd, pe, pf = parent.matrix
    la, lb, lc, ld, le, lf = local.matrix
    matrix = (
        pa * la + pc * lb,
        pb * la + pd * lb,
        pa * lc + pc * ld,
        pb * lc + pd * ld,
        pa * le + pc * lf + pe,
        pb * le + pd * lf + pf,
    )
    return TransformResolution(
        matrix=matrix,
        resolved=parent.resolved and local.resolved,
        evidence=f"Cumulative group transform: {parent.evidence} {local.evidence}",
        anchor_ids=parent.anchor_ids + local.anchor_ids,
    )


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
    stream: BinaryIO,
    page_id: str,
    replay_strategy: ReplayStrategy,
    text_anchor_layout: TextAnchorLayout | None,
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
    root_text_block = next(
        (block for block in reversed(blocks) if isinstance(block, RootTextBlock)), None
    )
    anchor_positions = _anchor_positions(
        root_text_block,
        scene_info.paper_size if scene_info is not None else None,
    )
    root_text_pos_y = (
        float(root_text_block.value.pos_y) if root_text_block is not None else None
    )
    group_items = {
        block.item.value: (index, block)
        for index, block in enumerate(blocks)
        if isinstance(block, SceneGroupItemBlock) and block.item.value is not None
    }
    parents = {node_id: block.parent_id for node_id, block in tree_blocks.items()}
    local_transforms = {
        node_id: _local_group_transform(
            group,
            anchor_positions,
            root_text_pos_y,
            text_anchor_layout,
        )
        for node_id, group in node_details.items()
    }
    effective_transforms: dict[CrdtId, TransformResolution] = {
        ROOT_ID: _identity_resolution("Scene root uses identity translation.")
    }

    def effective_transform(node_id: CrdtId, active: frozenset[CrdtId] = frozenset()):
        if node_id in effective_transforms:
            return effective_transforms[node_id]
        if node_id in active:
            result = TransformResolution(
                IDENTITY_TRANSFORM,
                False,
                f"Cycle detected while resolving group {node_id}; used identity translation.",
            )
            effective_transforms[node_id] = result
            return result
        local = local_transforms.get(node_id)
        if local is None:
            result = TransformResolution(
                IDENTITY_TRANSFORM,
                False,
                f"Missing metadata for group {node_id}; used identity translation.",
            )
            effective_transforms[node_id] = result
            return result
        parent_id = parents.get(node_id, ROOT_ID)
        parent = effective_transform(parent_id, active | {node_id})
        result = _compose_transforms(parent, local)
        effective_transforms[node_id] = result
        return result

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
        local_transform = local_transforms[node_id]
        resolved_transform = effective_transform(node_id)
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
                local_transform=local_transform,
                effective_transform=resolved_transform,
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
                effective_transform=effective_transform(block.parent_id),
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

    diagnostics = _block_diagnostics(blocks)
    unresolved_anchor_ids = sorted(
        {
            anchor_id
            for group in groups
            if not group.effective_transform.resolved
            for anchor_id in group.effective_transform.anchor_ids
        },
        key=lambda anchor_id: anchor_id.as_tuple(),
    )
    if unresolved_anchor_ids:
        local_resolution_by_anchor = {
            anchor_id: group.local_transform
            for group in groups
            if not group.local_transform.resolved
            for anchor_id in group.local_transform.anchor_ids
        }

        def unresolved_anchor_warning(anchor_id: CrdtIdentifier) -> str:
            resolution = local_resolution_by_anchor.get(anchor_id)
            if resolution is not None and (
                "heuristic text anchor" in resolution.evidence
                or "Unverified anchor type" in resolution.evidence
            ):
                tx, ty = resolution.matrix[-2:]
                return (
                    f"Unverified group anchor {anchor_id}; retained heuristic translation "
                    f"({tx}, {ty}). {resolution.evidence}"
                )
            return (
                f"Unresolved group anchor {anchor_id}; retained X origin and used zero Y."
            )

        diagnostics = PageDiagnostics(
            blocks=diagnostics.blocks,
            warnings=diagnostics.warnings
            + tuple(unresolved_anchor_warning(anchor_id) for anchor_id in unresolved_anchor_ids),
        )

    return NormalizedPage(
        page_id=page_id,
        paper_size=scene_info.paper_size if scene_info is not None else None,
        source_to_page_transform=None,
        groups=tuple(groups),
        strokes=tuple(strokes),
        tombstones=tombstones,
        compositing_order=compositing_order,
        replay_order=replay_order,
        metadata=metadata,
        diagnostics=diagnostics,
    )


def parse_page(
    source: Source,
    *,
    page_id: str | None = None,
    replay_strategy: ReplayStrategy = "crdt-order",
    text_anchor_layout: TextAnchorLayout | None = None,
) -> NormalizedPage:
    if replay_strategy not in ("crdt-order", "scene-order"):
        raise ValueError(f"unknown replay strategy: {replay_strategy}")
    if hasattr(source, "read"):
        if page_id is None:
            raise ValueError("page_id is required when parsing a binary stream")
        return _parse_stream(source, page_id, replay_strategy, text_anchor_layout)

    path = Path(source)
    resolved_page_id = page_id if page_id is not None else path.stem
    with path.open("rb") as stream:
        return _parse_stream(stream, resolved_page_id, replay_strategy, text_anchor_layout)


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
