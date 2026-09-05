"""Deterministic page rendering interfaces and baseline raster backends."""

from .pillow import PillowRenderer
from .protocol import Renderer
from .types import RenderOptions, Viewport, VisibilityState

__all__ = ["PillowRenderer", "RenderOptions", "Renderer", "Viewport", "VisibilityState"]
