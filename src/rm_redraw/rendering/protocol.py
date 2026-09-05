"""Renderer boundary kept independent from parser and replay implementations."""

from __future__ import annotations

from typing import Protocol

from PIL import Image

from .types import NormalizedPage, RenderOptions, VisibilityState


class Renderer(Protocol):
    def render(
        self,
        page: NormalizedPage,
        options: RenderOptions,
        visibility: VisibilityState,
    ) -> Image.Image: ...
