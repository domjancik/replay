"""Contracts for app-PNG pencil coverage, independent of private fixtures."""

import numpy as np

from rm_redraw.rendering.pencil import dab, pressure_coverage


def render(pressure=1, opacity=255):
    alpha = np.zeros((200, 600), dtype=np.uint8)
    for x in np.arange(10, 140, 0.5):
        dab(alpha, x, 25, 8.4, pressure, 4, 4, opacity)
    return alpha


def test_max_pressure_preserves_sparse_paper_holes_and_opaque_grains():
    a = render()[80:120, 80:500]
    assert np.any(a == 0)
    assert np.mean(a == 255) > 0.9
    assert np.mean(a == 0) < 0.08


def test_pressure_is_monotone_and_zero_is_blank():
    previous = render(0)
    assert not previous.any()
    for pressure in [0.25, 0.5, 0.75, 1]:
        a = render(pressure)
        assert np.all(a >= previous)
        assert a.sum() > previous.sum()
        previous = a
    assert pressure_coverage(-1) == 0
    assert pressure_coverage(2) == pressure_coverage(1) < 1


def test_deposition_is_idempotent_and_respects_source_alpha():
    a = render(opacity=100)
    before = a.copy()
    for x in np.arange(10, 140, 0.5):
        dab(a, x, 25, 8.4, 1, 4, 4, 100)
    assert np.array_equal(a, before)
    assert a.max() == 100


def test_boundary_remains_irregular_at_maximum_pressure():
    a = render()
    occupied = a[:, 80:500] > 0
    upper = np.argmax(occupied, axis=0)
    assert np.std(upper) > 1
    assert upper.min() > 45


def test_revealing_more_path_preserves_reached_prefix():
    alpha = np.zeros((200, 600), dtype=np.uint8)
    for x in np.arange(10, 70, 0.5):
        dab(alpha, x, 25, 8.4, 0.5, 4, 4, 255)
    prefix = alpha[:, :200].copy()
    assert not alpha[:, 400:].any()
    for x in np.arange(70, 140, 0.5):
        dab(alpha, x, 25, 8.4, 0.5, 4, 4, 255)
    assert np.array_equal(alpha[:, :200], prefix)


def test_cluster_coverage_varies_locally_without_changing_mean_to_solid_gray():
    from rm_redraw.rendering.pencil import coverage_threshold

    yy, xx = np.mgrid[0:256, 0:256]
    thresholds = coverage_threshold(xx + 0.5, yy + 0.5, 0.5)
    # A coarser occupancy field groups individual paper grains into islands.
    assert thresholds.std() > 0.05
    assert 0.37 < thresholds.mean() < 0.43
    assert np.array_equal(thresholds[:4, :4], np.full((4, 4), thresholds[0, 0]))
    assert np.array_equal(
        thresholds[41:97, 20:89],
        coverage_threshold(xx[41:97, 20:89] + 0.5, yy[41:97, 20:89] + 0.5, 0.5),
    )


def test_cluster_threshold_is_pressure_monotone_and_preserves_maximum_holes():
    from rm_redraw.rendering.pencil import coverage_threshold

    yy, xx = np.mgrid[0:40, 0:40]
    previous = coverage_threshold(xx + 0.5, yy + 0.5, 0)
    assert np.all(previous == 0)
    for pressure in np.linspace(0, 1, 33)[1:]:
        threshold = coverage_threshold(xx + 0.5, yy + 0.5, pressure)
        assert np.all(threshold >= previous - 1e-14)
        previous = threshold
    assert np.allclose(previous, 0.97)
