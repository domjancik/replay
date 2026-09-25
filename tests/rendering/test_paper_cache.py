"""Exact global phase, bounded retention and baseline bitmap compatibility."""

from hashlib import sha256

import numpy as np
import pytest

from rm_redraw.rendering.paper_cache import PaperFieldCache
from rm_redraw.rendering.pencil import _field, dab


def factory(x, y):
    return (
        _field(x, y, 1, 0),
        2 * _field(x, y, 1, 193) - 1,
        np.exp(0.5 * (2 * _field(x, y, 0.25, 917) - 1)),
    )


@pytest.mark.parametrize("scale", [(4, 4), (1.3333333333333333, 0.875)])
def test_cached_fields_equal_uncached_across_tile_edges_and_scales(scale):
    cache = PaperFieldCache(factory, tile_size=16, max_tiles=4)
    for bounds in [(2, 3, 12, 14), (13, 14, 31, 34), (-5, -2, 9, 11)]:
        left, top, right, bottom = bounds
        yy, xx = np.mgrid[top:bottom, left:right]
        expected = factory((xx + 0.5) / scale[0], (yy + 0.5) / scale[1])
        actual = cache.get(*bounds, *scale)
        assert all(np.array_equal(a, b) for a, b in zip(actual, expected, strict=True))


def test_cache_retention_is_bounded_and_repeated_tile_reuses_readonly_arrays():
    cache = PaperFieldCache(factory, tile_size=16, max_tiles=3)
    first = cache.get(0, 0, 8, 8, 4, 4)
    again = cache.get(0, 0, 8, 8, 4, 4)
    assert np.shares_memory(first[0], again[0])
    assert not first[0].flags.writeable
    for x in range(30):
        cache.get(x * 16, 0, x * 16 + 8, 8, 4, 4)
    assert cache.info().tiles <= 3
    assert cache.info().bytes <= 3 * 16 * 16 * 3 * 8
    assert cache.info().hits >= 1
    cache.clear()
    assert cache.info().tiles == cache.info().bytes == 0


@pytest.mark.parametrize(
    "sx,sy,expected",
    [
        (1, 1, "0f83aa85180b87544a925403fa77495484cd218587176b1b7e7b473fe0200bfc"),
        (4, 4, "a181752c859d1fa18a672674cb29c5ce0a6ca4938c7d54f071d510b84038214d"),
        (
            1.3333333333333333,
            0.875,
            "c5473585a78bbc73d8a3ac4668313ca1b6ea10a6f821fb3379607626c618efb8",
        ),
        (2.125, 3.75, "ebfb88ae28449e5ac19a25e583991a9f6f498ea32adb88cfbd177dded769ece3"),
    ],
)
def test_pencil_bitmap_is_byte_identical_to_fdaa8e7(sx, sy, expected):
    alpha = np.zeros((260, 340), np.uint8)
    for i in range(90):
        dab(alpha, -3 + i * 0.83, 12 + i * 0.13, 1 + (i % 13) * 0.7, (i % 31) / 30, sx, sy, 173)
    assert sha256(alpha.tobytes()).hexdigest() == expected


def test_local_alpha_origin_keeps_global_phase_and_clipping():
    full = np.zeros((260, 340), np.uint8)
    local = np.zeros((151, 173), np.uint8)
    for i in range(90):
        args = (-3 + i * 0.83, 12 + i * 0.13, 1 + (i % 13) * 0.7, (i % 31) / 30, 2.125, 3.75, 173)
        dab(full, *args)
        dab(local, *args, origin_x=17, origin_y=19)
    assert np.array_equal(local, full[19:170, 17:190])


def test_skinny_window_streams_tiles_without_pinning_evicted_backings():
    import weakref

    references = []
    peak = 0

    def tracked_factory(x, y):
        nonlocal peak
        result = factory(x, y)
        references.append(weakref.ref(result[0]))
        peak = max(peak, sum(ref() is not None for ref in references))
        return result

    cache = PaperFieldCache(tracked_factory, tile_size=8, max_tiles=2)
    fields = cache.get(0, 0, 256, 1, 4, 4)
    assert fields[0].shape == (1, 256)
    # Two retained tiles, current generated tile, and the initial view.
    assert peak <= 4
    with pytest.raises(ValueError, match="oversized"):
        cache.get(0, 0, 257, 1, 4, 4)
