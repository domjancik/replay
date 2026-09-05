from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

type ReplayStrategy = Literal["crdt-order", "scene-order"]


@dataclass(frozen=True, order=True)
class CrdtIdentifier:
    part1: int
    part2: int

    def as_tuple(self) -> tuple[int, int]:
        return (self.part1, self.part2)

    def __str__(self) -> str:
        return f"{self.part1}:{self.part2}"


@dataclass(frozen=True)
class VersionedValue:
    timestamp: CrdtIdentifier
    value: object


@dataclass(frozen=True)
class SceneOrder:
    item_id: CrdtIdentifier
    left_id: CrdtIdentifier
    right_id: CrdtIdentifier
    deleted_length: int
    block_index: int


@dataclass(frozen=True)
class EnumValue:
    code: int
    name: str | None


@dataclass(frozen=True)
class NormalizedPoint:
    x: float
    y: float
    pressure: int | float
    speed: int | float
    direction: int | float
    width: int | float
    extra: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedGroup:
    node_id: CrdtIdentifier
    source_node_id: CrdtIdentifier
    parent_id: CrdtIdentifier
    layer_id: CrdtIdentifier
    kind: Literal["layer", "group"]
    label: VersionedValue
    visible: VersionedValue
    scene_order: SceneOrder
    extra: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedStroke:
    stroke_id: CrdtIdentifier
    parent_id: CrdtIdentifier
    layer_id: CrdtIdentifier
    scene_order: SceneOrder
    move_id: CrdtIdentifier | None
    tool: EnumValue
    color: EnumValue
    color_rgba: tuple[int, int, int, int] | None
    thickness_scale: float
    starting_length: float
    points: tuple[NormalizedPoint, ...]
    extra: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ReplayOrder:
    strategy: ReplayStrategy
    stroke_ids: tuple[CrdtIdentifier, ...]
    evidence: str


@dataclass(frozen=True)
class NormalizedTombstone:
    tombstone_id: CrdtIdentifier
    parent_id: CrdtIdentifier
    scene_order: SceneOrder


@dataclass(frozen=True)
class MigrationMetadata:
    migration_id: CrdtIdentifier
    is_device: bool
    unknown: bool


@dataclass(frozen=True)
class PageInfoMetadata:
    loads_count: int
    merges_count: int
    text_chars_count: int
    text_lines_count: int
    type_folio_use_count: int


@dataclass(frozen=True)
class PageMetadata:
    current_layer: VersionedValue | None
    background_visible: VersionedValue | None
    root_document_visible: VersionedValue | None
    authors: dict[int, str]
    migrations: tuple[MigrationMetadata, ...]
    page_info: PageInfoMetadata | None


@dataclass(frozen=True)
class BlockDiagnostic:
    block_index: int
    block_type: int
    block_name: str
    unreadable: bool
    error: str | None
    raw_data_base64: str | None
    extra_data_base64: str | None
    extra_value_data_base64: str | None
    fields: dict[str, object]


@dataclass(frozen=True)
class PageDiagnostics:
    blocks: tuple[BlockDiagnostic, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class NormalizedPage:
    page_id: str
    paper_size: tuple[int, int] | None
    source_to_page_transform: tuple[float, float, float, float, float, float]
    groups: tuple[NormalizedGroup, ...]
    strokes: tuple[NormalizedStroke, ...]
    tombstones: tuple[NormalizedTombstone, ...]
    compositing_order: tuple[CrdtIdentifier, ...]
    replay_order: ReplayOrder
    metadata: PageMetadata
    diagnostics: PageDiagnostics
