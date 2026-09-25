import pytest

from rm_redraw.web.export import crop_bounds, replay_indices


def test_crop_snaps_to_even_pixels_without_leaving_image():
    assert crop_bounds([11, 13, 51, 41], (100, 80)) == (10, 12, 60, 52)
    with pytest.raises(ValueError):
        crop_bounds([90, 0, 20, 20], (100, 80))


def test_quick_reverse_skips_end_hold_and_returns_to_first_frame():
    indices = replay_indices(14, 4, 4)
    assert indices[:14] == list(range(14))
    assert indices[14:] == [8, 4, 0]
    assert replay_indices(14, 4, 0) == list(range(14))


def test_crop_loop_export_from_saved_frames(tmp_path):
    import json
    import subprocess

    from PIL import Image

    from rm_redraw.replay.output import write_png
    from rm_redraw.web.export import export_replay

    source = tmp_path / "source"
    source.mkdir()
    entries = []
    for i in range(14):
        image = Image.new("RGBA", (100, 80), (min(i, 9) * 20, 30, 40, 255))
        path = write_png(image, source / "frames" / f"frame_{i:06d}.png")
        entries.append({"path": path.relative_to(source).as_posix()})
    write_png(image, source / "static.png")
    (source / "manifest.json").write_text(
        json.dumps({"frames": entries, "replay": {"fps": 4, "final_hold_seconds": 1}})
    )
    output = tmp_path / "export"
    export_replay(source, output, [11, 13, 51, 41], 4)
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["frame_count"] == 17
    assert manifest["forward_final_frame_matches_static"]
    assert manifest["loop_seam_matches"]
    assert not manifest["final_frame_matches_static"]
    assert Image.open(output / "static.png").size == (50, 40)
    assert (output / "video-frames/frame_000016.png").read_bytes() == (
        output / "video-frames/frame_000000.png"
    ).read_bytes()
    probe = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=width,height,nb_frames",
                "-of",
                "json",
                str(output / "replay.mp4"),
            ]
        )
    )
    assert probe["streams"][0] == {"width": 50, "height": 40, "nb_frames": "17"}


@pytest.mark.parametrize("speed", [False, True, 4.0, "4", None])
def test_reverse_speed_rejects_non_integer_values(speed):
    with pytest.raises(ValueError):
        replay_indices(14, 4, speed)
