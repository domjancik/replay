from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from io import BytesIO

import pytest
from PIL import Image
from rmscene import (
    CrdtId,
    CrdtSequenceItem,
    LwwValue,
    SceneGroupItemBlock,
    SceneInfo,
    SceneLineItemBlock,
    SceneTreeBlock,
    TreeNodeBlock,
    write_blocks,
)
from rmscene import scene_items as si

from rm_redraw.replay.__main__ import main
from rm_redraw.replay.command import ReplayCommandError, run_local_replay

END = CrdtId(0, 0)
ROOT = CrdtId(0, 1)


def _page_bytes(*, paper_size: tuple[int, int] | None, stroke_count: int = 1) -> bytes:
    layer_id = CrdtId(4, 10)
    blocks = [
        SceneInfo(
            current_layer=LwwValue(CrdtId(4, 1), layer_id),
            background_visible=LwwValue(CrdtId(4, 2), True),
            root_document_visible=LwwValue(CrdtId(4, 3), True),
            paper_size=paper_size,
        ),
        SceneTreeBlock(layer_id, layer_id, False, ROOT),
        TreeNodeBlock(
            si.Group(
                node_id=layer_id,
                label=LwwValue(CrdtId(4, 4), "Ink"),
                visible=LwwValue(CrdtId(4, 5), True),
            )
        ),
        SceneGroupItemBlock(ROOT, CrdtSequenceItem(CrdtId(4, 11), END, END, 0, layer_id)),
        *[
            SceneLineItemBlock(
                layer_id,
                CrdtSequenceItem(
                    CrdtId(4, 12 + index),
                    END,
                    END,
                    0,
                    si.Line(
                        color=si.PenColor.BLACK,
                        tool=si.Pen.BALLPOINT_2,
                        points=[
                            si.Point(4, 8 + index, 1, 1, 1, 1),
                            si.Point(28, 20 + index, 1, 1, 1, 1),
                        ],
                        thickness_scale=2.0,
                        starting_length=0.0,
                    ),
                ),
            )
            for index in range(stroke_count)
        ],
    ]
    stream = BytesIO()
    write_blocks(stream, blocks, options={"version": "3.27.3"})
    return stream.getvalue()


def test_multi_page_archive_requires_explicit_page_id(tmp_path) -> None:
    archive = tmp_path / "notebook.rmdoc"
    with zipfile.ZipFile(archive, "w") as document:
        document.writestr("first.rm", _page_bytes(paper_size=(64, 48)))
        document.writestr("second.rm", _page_bytes(paper_size=(64, 48)))

    with pytest.raises(ReplayCommandError, match="--page-id"):
        run_local_replay(archive, output_directory=tmp_path / "output")


def test_missing_source_paper_size_requires_explicit_override(tmp_path) -> None:
    source = tmp_path / "page.rm"
    source.write_bytes(_page_bytes(paper_size=None))

    with pytest.raises(ReplayCommandError, match="--paper-size"):
        run_local_replay(source, output_directory=tmp_path / "output")


def test_missing_source_affine_requires_explicit_override(tmp_path) -> None:
    source = tmp_path / "page.rm"
    source.write_bytes(_page_bytes(paper_size=(64, 48)))

    with pytest.raises(ReplayCommandError, match="--source-affine"):
        run_local_replay(source, output_directory=tmp_path / "output")


def test_paired_export_canvas_resolves_missing_page_geometry(tmp_path) -> None:
    source = tmp_path / "page.rm"
    source.write_bytes(_page_bytes(paper_size=None))
    native_pdf = tmp_path / "native.pdf"
    Image.new("RGB", (594, 1946), "white").save(native_pdf, "PDF")

    result = run_local_replay(
        source,
        output_directory=tmp_path / "output",
        paired_native_pdf=native_pdf,
        paired_pdf_page=1,
        export_canvas=(1872, 6136),
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["geometry"]["paper_size"] == [1872, 6136]
    assert manifest["geometry"]["source_to_page_transform"] == [1.0, 0.0, 0.0, 1.0, 936.0, 0.0]
    assert manifest["geometry"]["paper_size_evidence"] == (
        "Paired native PDF export canvas; SceneInfo.paper_size was absent."
    )
    assert manifest["geometry"]["transform_evidence"] == (
        "Centered source frame inferred from paired native PDF export canvas width."
    )
    assert manifest["paired_export"]["canvas"] == {"width": 1872, "height": 6136}
    assert manifest["paired_export"]["native_pdf"]["page"] == 1


def test_cli_accepts_locally_verifiable_paired_export_canvas(tmp_path) -> None:
    source = tmp_path / "page.rm"
    source.write_bytes(_page_bytes(paper_size=None))
    native_pdf = tmp_path / "native.pdf"
    Image.new("RGB", (594, 1946), "white").save(native_pdf, "PDF")
    output = tmp_path / "output"

    exit_code = main(
        [
            str(source),
            "--output",
            str(output),
            "--paired-native-pdf",
            str(native_pdf),
            "--paired-pdf-page",
            "1",
            "--export-canvas",
            "1872",
            "6136",
        ]
    )

    assert exit_code == 0
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["paired_export"]["native_pdf"]["media_box_points"] == {
        "width": 594.0,
        "height": 1946.0,
    }


def test_paired_export_canvas_rejects_fractional_dimensions(tmp_path) -> None:
    source = tmp_path / "page.rm"
    source.write_bytes(_page_bytes(paper_size=None))
    native_pdf = tmp_path / "native.pdf"
    Image.new("RGB", (594, 1946), "white").save(native_pdf, "PDF")

    with pytest.raises(ReplayCommandError, match=r"--export-canvas.*positive integers"):
        run_local_replay(
            source,
            output_directory=tmp_path / "output",
            paired_native_pdf=native_pdf,
            export_canvas=(1872.5, 6136),
        )


def test_paired_export_rejects_malformed_native_pdf_actionably(tmp_path) -> None:
    source = tmp_path / "page.rm"
    source.write_bytes(_page_bytes(paper_size=None))
    native_pdf = tmp_path / "native.pdf"
    native_pdf.write_bytes(b"not a PDF")

    with pytest.raises(ReplayCommandError, match="cannot validate paired native PDF page 1"):
        run_local_replay(
            source,
            output_directory=tmp_path / "output",
            paired_native_pdf=native_pdf,
            export_canvas=(1872, 6136),
        )


def test_stale_scene_paper_size_requires_explicit_canvas_selection(tmp_path) -> None:
    source = tmp_path / "page.rm"
    source.write_bytes(_page_bytes(paper_size=(1404, 1872)))
    native_pdf = tmp_path / "native.pdf"
    Image.new("RGB", (594, 1946), "white").save(native_pdf, "PDF")

    with pytest.raises(ReplayCommandError, match=r"SceneInfo\.paper_size conflicts.*--paper-size"):
        run_local_replay(
            source,
            output_directory=tmp_path / "output",
            paired_native_pdf=native_pdf,
            export_canvas=(1872, 6136),
        )


def test_fractional_paper_size_override_reports_the_cli_option(tmp_path) -> None:
    source = tmp_path / "page.rm"
    source.write_bytes(_page_bytes(paper_size=(64, 48)))

    with pytest.raises(ReplayCommandError, match=r"--paper-size.*positive finite integers"):
        run_local_replay(
            source,
            output_directory=tmp_path / "output",
            paper_size=(64.5, 48),
            source_affine=(1, 0, 0, 1, 0, 0),
        )


def test_local_archive_replay_writes_hashed_manifest_and_equal_final_frame(tmp_path) -> None:
    archive = tmp_path / "notebook.rmdoc"
    page_bytes = _page_bytes(paper_size=(64, 48))
    with zipfile.ZipFile(archive, "w") as document:
        document.writestr("selected-page.rm", page_bytes)

    result = run_local_replay(
        archive,
        page_id="selected-page",
        output_directory=tmp_path / "replay-output",
        mode="seconds-per-stroke",
        fps=2,
        seconds_per_stroke=0.5,
        source_affine=(1, 0, 0, 1, 3, 4),
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert (result.output_directory / "frames" / "frame_000000.png").is_file()
    assert (result.output_directory / "static.png").is_file()
    assert (result.output_directory / "replay.mp4").read_bytes()[4:8] == b"ftyp"
    assert manifest["input"]["sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert manifest["input"]["page_member"] == "selected-page.rm"
    assert manifest["input"]["page_sha256"] == hashlib.sha256(page_bytes).hexdigest()
    assert manifest["geometry"]["source_to_page_transform"][4:] == [3.0, 4.0]
    assert manifest["geometry"]["transform_evidence"] == (
        "Caller-supplied source_to_page_transform; parsed source metadata was absent."
    )
    assert manifest["replay"]["mode"] == "seconds-per-stroke"
    assert manifest["viewport"] == {"height": 48, "width": 64}
    assert manifest["backend"]["palette_profile"] == "native-basic-3.28-v1"
    assert manifest["backend"]["palette_calibrated_codes"] == [0, 1, 3, 6, 7]
    assert manifest["backend"]["simple_profile"] == "current-simple-geometry-v1"
    assert manifest["backend"]["marker_profile"] == "provisional-marker-envelope-v1"
    assert manifest["backend"]["highlighter_blend_scope"] == "within-layer-darken"
    assert manifest["video"]["path"] == "replay.mp4"
    assert (
        manifest["video"]["sha256"]
        == hashlib.sha256((result.output_directory / "replay.mp4").read_bytes()).hexdigest()
    )
    assert manifest["final_frame_matches_static"] is True
    assert manifest["frames"][-1]["sha256"] == manifest["static"]["sha256"]


def test_stroke_step_manifest_times_match_encoded_fps(tmp_path) -> None:
    source = tmp_path / "page.rm"
    source.write_bytes(_page_bytes(paper_size=(64, 48), stroke_count=2))

    result = run_local_replay(
        source,
        output_directory=tmp_path / "output",
        source_affine=(1, 0, 0, 1, 0, 0),
        mode="stroke-step",
        fps=4,
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert [frame["time_seconds"] for frame in manifest["frames"]] == [0.0, 0.25]
    assert manifest["frames"][-1]["time_seconds"] == (manifest["frame_count"] - 1) / 4


@pytest.mark.parametrize(
    ("mode", "timing"),
    [
        ("seconds-per-stroke", {"seconds_per_stroke": 0.5}),
        ("distance-per-second", {"distance_per_second": 1000}),
    ],
)
def test_progressive_manifest_times_match_encoded_fps(tmp_path, mode, timing) -> None:
    source = tmp_path / "page.rm"
    source.write_bytes(_page_bytes(paper_size=(64, 48), stroke_count=2))

    result = run_local_replay(
        source,
        output_directory=tmp_path / "output",
        source_affine=(1, 0, 0, 1, 0, 0),
        mode=mode,
        fps=4,
        **timing,
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert [frame["time_seconds"] for frame in manifest["frames"]] == [
        index / 4 for index in range(manifest["frame_count"])
    ]


def test_progressive_manifest_records_inferred_pacing_and_holds(tmp_path) -> None:
    source = tmp_path / "page.rm"
    source.write_bytes(_page_bytes(paper_size=(64, 48), stroke_count=2))

    result = run_local_replay(
        source,
        output_directory=tmp_path / "output",
        source_affine=(1, 0, 0, 1, 0, 0),
        mode="seconds-per-stroke",
        fps=2,
        seconds_per_stroke=0.5,
        initial_pause_seconds=1,
        pause_between_strokes_seconds=0.5,
        final_hold_seconds=1,
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["replay"]["timing_evidence"] == (
        "Synthesized timing; source point wall-clock timestamps are unavailable."
    )
    assert manifest["replay"]["initial_pause_seconds"] == 1
    assert manifest["replay"]["pause_between_strokes_seconds"] == 0.5
    assert manifest["replay"]["final_hold_seconds"] == 1
    assert manifest["frame_count"] == 7
    assert manifest["final_frame_matches_static"] is True


def test_progressive_hold_timing_must_be_finite_and_nonnegative(tmp_path) -> None:
    source = tmp_path / "page.rm"
    source.write_bytes(_page_bytes(paper_size=(64, 48)))

    with pytest.raises(ReplayCommandError, match="--initial-pause"):
        run_local_replay(
            source,
            output_directory=tmp_path / "output",
            source_affine=(1, 0, 0, 1, 0, 0),
            mode="seconds-per-stroke",
            seconds_per_stroke=1,
            initial_pause_seconds=float("nan"),
        )


@pytest.mark.parametrize(
    ("mode", "timing", "option"),
    [
        ("seconds-per-stroke", {"seconds_per_stroke": 0}, "--seconds-per-stroke"),
        ("distance-per-second", {"distance_per_second": 0}, "--distance-per-second"),
    ],
)
def test_progressive_timing_must_be_positive(tmp_path, mode, timing, option) -> None:
    source = tmp_path / "page.rm"
    source.write_bytes(_page_bytes(paper_size=(64, 48)))

    with pytest.raises(ReplayCommandError, match=option):
        run_local_replay(
            source,
            output_directory=tmp_path / "output",
            source_affine=(1, 0, 0, 1, 0, 0),
            mode=mode,
            **timing,
        )


def test_invalid_viewport_reports_cli_option(tmp_path) -> None:
    source = tmp_path / "page.rm"
    source.write_bytes(_page_bytes(paper_size=(64, 48)))

    with pytest.raises(ReplayCommandError, match="--viewport"):
        run_local_replay(
            source,
            output_directory=tmp_path / "output",
            source_affine=(1, 0, 0, 1, 0, 0),
            viewport=(0, 48),
        )


def test_output_directory_must_be_new(tmp_path) -> None:
    source = tmp_path / "page.rm"
    source.write_bytes(_page_bytes(paper_size=(64, 48)))
    output = tmp_path / "existing-output"
    output.mkdir()

    with pytest.raises(ReplayCommandError, match="new output directory"):
        run_local_replay(source, output_directory=output, source_affine=(1, 0, 0, 1, 0, 0))


def test_encoder_failure_reports_actionable_replay_error(tmp_path, monkeypatch) -> None:
    source = tmp_path / "page.rm"
    source.write_bytes(_page_bytes(paper_size=(64, 48)))

    def fail_encoding(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, "ffmpeg", stderr=b"encoder detail")

    monkeypatch.setattr("rm_redraw.replay.command.encode_h264", fail_encoding)

    with pytest.raises(ReplayCommandError, match="H.264 encoding failed"):
        run_local_replay(
            source,
            output_directory=tmp_path / "output",
            source_affine=(1, 0, 0, 1, 0, 0),
        )


def test_duration_cli_limits_frames_even_with_many_strokes(tmp_path):
    source = tmp_path / "page.rm"
    source.write_bytes(_page_bytes(paper_size=(64, 64), stroke_count=20))
    output = tmp_path / "duration"
    assert (
        main(
            [
                str(source),
                "--output",
                str(output),
                "--source-affine",
                "1",
                "0",
                "0",
                "1",
                "0",
                "0",
                "--mode",
                "duration",
                "--duration",
                "2",
                "--fps",
                "4",
                "--final-hold",
                "0.5",
            ]
        )
        == 0
    )
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["frame_count"] == 10
    assert manifest["replay"]["duration_seconds"] == 2
    assert manifest["final_frame_matches_static"]
    assert (output / "frames/frame_000009.png").read_bytes() == (output / "static.png").read_bytes()
