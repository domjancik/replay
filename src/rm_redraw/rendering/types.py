"""Small immutable normalized-page adapters used by rendering and replay."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

Color = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class NormalizedPoint:
    x: float
    y: float
    pressure: float = 1.0
    speed: float | None = None
    direction: float | None = None
    width: float | None = None
    extra: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NormalizedStroke:
    stroke_id: str
    group_id: str
    rgba: Color
    thickness_scale: float
    points: tuple[NormalizedPoint, ...]
    tool_code: int | None = None
    tool_name: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedGroup:
    group_id: str
    visible: bool = True


@dataclass(frozen=True, slots=True)
class NormalizedPage:
    page_id: str
    paper_size: tuple[float, float] | None
    groups: tuple[NormalizedGroup, ...]
    strokes: tuple[NormalizedStroke, ...]
    compositing_order: tuple[str, ...]
    replay_order: tuple[str, ...]
    replay_strategy: str
    replay_evidence: str


@dataclass(frozen=True, slots=True)
class Viewport:
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("viewport dimensions must be positive")


@dataclass(frozen=True, slots=True)
class RenderOptions:
    viewport: Viewport | None = None
    background: Color = (255, 255, 255, 255)
    pencil_boundary: bool = False
    pencil_backend: str = "python"

    def __post_init__(self) -> None:
        if self.pencil_backend not in ("python", "rust"):
            raise ValueError("pencil backend must be python or rust")
        if self.pencil_backend == "rust" and self.pencil_boundary:
            raise ValueError("Rust pencil backend requires the current app-PNG profile")


@dataclass(frozen=True, slots=True)
class VisibilityState:
    completed_stroke_ids: frozenset[str] = frozenset()
    active_stroke_id: str | None = None
    active_progress: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.active_progress <= 1.0:
            raise ValueError("active progress must be between zero and one")
