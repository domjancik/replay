"""Bounded, exact-phase tile storage for pressure-independent paper fields."""

from collections import OrderedDict
from collections.abc import Callable, Iterator
from itertools import chain
from threading import Lock
from typing import NamedTuple

import numpy as np

Fields = tuple[np.ndarray, np.ndarray, np.ndarray]


class CacheInfo(NamedTuple):
    tiles: int
    bytes: int
    hits: int
    misses: int


class PaperFieldCache:
    """LRU field tiles; coordinates are temporary one-dimensional vectors.

    Retained storage is at most max_tiles * tile_size**2 * 3 * 8 bytes.
    Region iteration avoids assembling oversized windows: each yielded view
    has at most one tile's pixels. get() assembles at most four tile areas and
    rejects larger requests; production dab code uses region iteration.
    """

    def __init__(
        self,
        factory: Callable[[np.ndarray, np.ndarray], Fields],
        *,
        tile_size: int = 128,
        max_tiles: int = 64,
    ):
        if tile_size < 1 or max_tiles < 1:
            raise ValueError("tile_size and max_tiles must be positive")
        self.factory = factory
        self.tile_size = tile_size
        self.max_tiles = max_tiles
        self._tiles: OrderedDict[tuple[int, int, float, float], Fields] = OrderedDict()
        self._lock = Lock()
        self._hits = 0
        self._misses = 0

    def _tile(self, tx: int, ty: int, sx: float, sy: float) -> Fields:
        key = (tx, ty, sx, sy)
        with self._lock:
            value = self._tiles.get(key)
            if value is not None:
                self._tiles.move_to_end(key)
                self._hits += 1
                return value
            self._misses += 1
        n = self.tile_size
        x = (np.arange(tx * n, (tx + 1) * n)[None, :] + 0.5) / sx
        y = (np.arange(ty * n, (ty + 1) * n)[:, None] + 0.5) / sy
        value = self.factory(x, y)
        for array in value:
            if array.shape != (n, n) or array.dtype != np.float64:
                raise ValueError("paper fields must be float64 tile arrays")
            array.flags.writeable = False
        with self._lock:
            # Another caller may have generated this tile concurrently.
            existing = self._tiles.get(key)
            if existing is not None:
                return existing
            self._tiles[key] = value
            while len(self._tiles) > self.max_tiles:
                self._tiles.popitem(last=False)
        return value

    def regions(
        self, left: int, top: int, right: int, bottom: int, sx: float, sy: float
    ) -> Iterator[tuple[int, int, int, int, Fields]]:
        if right <= left or bottom <= top:
            return
        n = self.tile_size
        for ty in range(top // n, (bottom - 1) // n + 1):
            for tx in range(left // n, (right - 1) // n + 1):
                region_left, region_top = max(left, tx * n), max(top, ty * n)
                region_right, region_bottom = min(right, (tx + 1) * n), min(bottom, (ty + 1) * n)
                fields = self._tile(tx, ty, sx, sy)
                yield (
                    region_left,
                    region_top,
                    region_right,
                    region_bottom,
                    tuple(
                        a[
                            region_top - ty * n : region_bottom - ty * n,
                            region_left - tx * n : region_right - tx * n,
                        ]
                        for a in fields
                    ),
                )

    def get(self, left: int, top: int, right: int, bottom: int, sx: float, sy: float) -> Fields:
        if right <= left or bottom <= top:
            raise ValueError("paper field window must be nonempty")
        if (right - left) * (bottom - top) > 4 * self.tile_size**2:
            raise ValueError("oversized paper field window; iterate regions instead")
        regions = self.regions(left, top, right, bottom, sx, sy)
        first = next(regions)
        if first[:4] == (left, top, right, bottom):
            return first[4]
        result = tuple(np.empty((bottom - top, right - left), dtype=np.float64) for _ in range(3))
        for region_left, region_top, region_right, region_bottom, fields in chain(
            (first,), regions
        ):
            for dst, src in zip(result, fields, strict=True):
                dst[
                    region_top - top : region_bottom - top, region_left - left : region_right - left
                ] = src
        return result

    def info(self) -> CacheInfo:
        with self._lock:
            return CacheInfo(
                len(self._tiles),
                sum(a.nbytes for v in self._tiles.values() for a in v),
                self._hits,
                self._misses,
            )

    def clear(self) -> None:
        with self._lock:
            self._tiles.clear()
            self._hits = self._misses = 0
