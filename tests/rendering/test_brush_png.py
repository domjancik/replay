import numpy as np

from rm_redraw.rendering.brush import brush_coverage


def fields():
    y, x = np.mgrid[0:30:0.25, 0:200:0.25]
    return x, y, 8 - abs(y - 15)


def test_low_pressure_is_broken_and_high_pressure_filled():
    x, y, distance = fields()
    low = brush_coverage(x, y, 64 / 255, distance, 4)
    high = brush_coverage(x, y, 1, distance, 4)
    interior = distance > 2
    assert 0.15 < low[interior].mean() < 0.5
    assert np.any(low[interior] == 0)
    assert np.any(low[interior] == 1)
    assert np.all(high[interior] == 1)
    assert np.all(high[interior] >= low[interior])
    assert high.sum() > low.sum()


def test_brush_grain_is_source_stable_and_has_fuzzy_edge():
    x, y, distance = fields()
    whole = brush_coverage(x, y, 1, distance, 4)
    cropped = brush_coverage(x[:, :201], y[:, :201], 1, distance[:, :201], 4)
    np.testing.assert_array_equal(whole[:, :201], cropped)
    assert np.any((whole > 0) & (whole < 1))
    assert np.any(whole[distance < 0] > 0)
    assert np.all(whole[distance < -1] == 0)


def test_zero_pressure_is_blank_and_output_is_bounded():
    x, y, distance = fields()
    assert not brush_coverage(x, y, 0, distance, 4).any()
    for pressure in np.linspace(0, 1, 17):
        a = brush_coverage(x, y, pressure, distance, 4)
        assert a.min() >= 0 and a.max() <= 1
