"""Generate synthetic WASM inputs and check the masks against native Rust and Python."""

import json
from hashlib import sha256
from pathlib import Path

import numpy as np

from rm_redraw.rendering.native_pencil import _gain_table, _pressure_knots, draw_batch
from rm_redraw.rendering.pencil import dab


def synthetic_samples(count, origin_x, origin_y, step_x, step_y, radius, radius_step):
    return [
        (
            origin_x + i * step_x,
            origin_y + i * step_y + (i % 19) * 0.23,
            radius + (i % 13) * radius_step,
            (i % 31) / 30,
        )
        for i in range(count)
    ]


def main():
    output = Path(__file__).resolve().parents[2] / "artifacts/wasm-feasibility-20261113/goldens"
    output.mkdir(parents=True, exist_ok=True)
    _gain_table().astype("<f8").tofile(output / "gains.f64")
    knots, coverages = _pressure_knots()
    controls = [(0.1, 0.2, 0.7, 0.25), (1.8, 1.1, 0.45, 0.75), (2.7, 0.9, 0.6, 1)]
    cases = [
        ("center", 1, 1, 0, 0, 1, 1, 173, 0, [(0.5, 0.5, 1.4, 1)]),
        ("zero-pressure", 1, 1, 0, 0, 1, 1, 173, 19, [(0.5, 0.5, 1.4, 0)]),
        ("negative-origin", 9, 7, -2, -1, 1.3333333333333333, 2.125, 173, 0, controls),
        (
            "overlap-and-tile-boundaries",
            173,
            151,
            17,
            19,
            4,
            4,
            173,
            11,
            synthetic_samples(90, 2, 12, 0.83, 0.13, 1, 0.7),
        ),
        (
            "broad-unequal-scales",
            384,
            256,
            -17,
            -19,
            2.125,
            3.75,
            227,
            0,
            synthetic_samples(400, 5, 5, 0.41, 0.13, 11, 1.2),
        ),
        (
            "larger-viewport",
            702,
            936,
            0,
            0,
            1.5,
            2.75,
            173,
            0,
            synthetic_samples(1200, 1, 2, 0.37, 0.26, 1, 0.37),
        ),
    ]
    metadata = []
    for name, width, height, x, y, sx, sy, opacity, initial, samples in cases:
        base = np.full((height, width), initial, dtype=np.uint8)
        python = base.copy()
        native = base.copy()
        for sample in samples:
            dab(python, *sample, sx, sy, opacity, origin_x=x, origin_y=y)
        draw_batch(native, samples, sx, sy, opacity, origin_x=x, origin_y=y)
        np.testing.assert_array_equal(native, python, err_msg=name)
        assert bool(np.any(python != base)) == (name != "zero-pressure"), name
        base.tofile(output / f"{name}.initial")
        python.tofile(output / f"{name}.mask")
        data = np.array(samples, dtype=np.float64)
        data[:, 3] = np.interp(data[:, 3], knots, coverages) / 0.97
        metadata.append(
            {
                "name": name,
                "width": width,
                "height": height,
                "originX": x,
                "originY": y,
                "scaleX": sx,
                "scaleY": sy,
                "opacity": opacity,
                "initial": initial,
                "samples": data.tolist(),
                "sha256": sha256(python.tobytes()).hexdigest(),
            }
        )
    (output / "cases.json").write_text(json.dumps(metadata), encoding="utf-8")


if __name__ == "__main__":
    main()
