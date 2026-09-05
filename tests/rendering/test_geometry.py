from rm_redraw.rendering.geometry import prefix_points
from rm_redraw.rendering.types import NormalizedPoint, NormalizedStroke


def test_prefix_interpolates_all_numeric_point_channels() -> None:
    stroke = NormalizedStroke(
        stroke_id="stroke",
        group_id="layer",
        rgba=(0, 0, 0, 255),
        thickness_scale=1,
        points=(
            NormalizedPoint(0, 0, pressure=0, speed=2, direction=4, width=6),
            NormalizedPoint(10, 0, pressure=10, speed=12, direction=14, width=16),
        ),
    )

    point = prefix_points(stroke, 0.5)[-1]

    assert (point.x, point.y) == (5, 0)
    assert (point.pressure, point.speed, point.direction, point.width) == (5, 7, 9, 11)
