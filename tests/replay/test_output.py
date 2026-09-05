from __future__ import annotations

from rm_redraw.rendering.pillow import PillowRenderer
from rm_redraw.rendering.types import (
    NormalizedGroup,
    NormalizedPage,
    NormalizedPoint,
    NormalizedStroke,
    RenderOptions,
)
from rm_redraw.replay.output import encode_h264, render_png_sequence, write_png
from rm_redraw.replay.schedule import progressive_distance_schedule


def _page() -> NormalizedPage:
    return NormalizedPage(
        page_id="output-page",
        paper_size=(32, 24),
        groups=(NormalizedGroup("lower"), NormalizedGroup("upper")),
        strokes=(
            NormalizedStroke(
                stroke_id="lower-line",
                group_id="lower",
                rgba=(20, 40, 60, 128),
                thickness_scale=3,
                points=(NormalizedPoint(2, 12), NormalizedPoint(30, 12)),
            ),
            NormalizedStroke(
                stroke_id="upper-line",
                group_id="upper",
                rgba=(90, 30, 10, 180),
                thickness_scale=2,
                points=(NormalizedPoint(16, 2), NormalizedPoint(16, 22)),
            ),
        ),
        compositing_order=("lower", "upper"),
        replay_order=("upper-line", "lower-line"),
        replay_strategy="scene-order",
        replay_evidence="synthetic interleaved layer fixture",
    )


def test_png_sequence_is_repeatable_and_final_frame_equals_static_render(tmp_path) -> None:
    page = _page()
    renderer = PillowRenderer()
    frames = progressive_distance_schedule(page, fps=4, drawing_speed=14)

    first = render_png_sequence(renderer, page, RenderOptions(), frames, tmp_path / "first")
    second = render_png_sequence(renderer, page, RenderOptions(), frames, tmp_path / "second")
    static_path = write_png(renderer.render_static(page, RenderOptions()), tmp_path / "static.png")

    assert [path.read_bytes() for path in first] == [path.read_bytes() for path in second]
    assert first[-1].read_bytes() == static_path.read_bytes()


def test_encoder_writes_h264_mp4_from_png_sequence(tmp_path) -> None:
    page = _page()
    frames = progressive_distance_schedule(page, fps=4, drawing_speed=14)
    sequence = render_png_sequence(
        PillowRenderer(), page, RenderOptions(), frames, tmp_path / "frames"
    )

    video = encode_h264(sequence, fps=4, output_path=tmp_path / "replay.mp4")

    assert video.read_bytes()[4:8] == b"ftyp"
