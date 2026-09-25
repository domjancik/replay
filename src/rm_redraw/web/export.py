"""Crop saved lossless frames and optionally append a fast reverse leg."""

import argparse
import hashlib
import json
import math
import os
import shutil
from pathlib import Path

from PIL import Image

from rm_redraw.replay.output import encode_h264, write_png


def crop_bounds(crop, size):
    if crop is None:
        return (0, 0, *size)
    if (
        not isinstance(crop, list)
        or len(crop) != 4
        or any(
            isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v)
            for v in crop
        )
    ):
        raise ValueError("Crop must contain finite x, y, width and height values")
    x, y, width, height = crop
    if x < 0 or y < 0 or width < 2 or height < 2 or x + width > size[0] or y + height > size[1]:
        raise ValueError("Crop must lie inside the image and be at least 2 by 2 pixels")
    left, top = math.floor(x / 2) * 2, math.floor(y / 2) * 2
    return left, top, left + math.floor(width / 2) * 2, top + math.floor(height / 2) * 2


def replay_indices(frame_count, hold_frames, reverse_speed):
    if type(reverse_speed) is not int or reverse_speed not in (0, 2, 4, 8):
        raise ValueError("Reverse speed must be off, 2x, 4x or 8x")
    result = list(range(frame_count))
    if reverse_speed and frame_count > 1:
        last_drawing = max(0, frame_count - hold_frames - 1)
        reverse = list(range(last_drawing - 1, -1, -reverse_speed))
        if not reverse or reverse[-1] != 0:
            reverse.append(0)
        result.extend(reverse)
    return result


def export_replay(source: Path, output: Path, crop=None, reverse_speed=0):
    original = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if original.get("export"):
        raise ValueError("Make each crop/loop from the original replay")
    fps = original["replay"]["fps"]
    with Image.open(source / "static.png") as static:
        bounds = crop_bounds(crop, static.size)
        final = static.crop(bounds)
    indices = replay_indices(
        len(original["frames"]),
        math.ceil(original["replay"]["final_hold_seconds"] * fps),
        reverse_speed,
    )
    output.mkdir(parents=True, exist_ok=False)
    static_path = write_png(final, output / "static.png")
    forward = []
    for index, entry in enumerate(original["frames"]):
        with Image.open(source / entry["path"]) as image:
            path = write_png(image.crop(bounds), output / "frames" / f"frame_{index:06d}.png")
        forward.append(path)
    if forward[-1].read_bytes() != static_path.read_bytes():
        raise ValueError("Cropped forward final frame does not match cropped static output")
    sequence = []
    video_folder = output / "video-frames"
    video_folder.mkdir()
    for index, source_index in enumerate(indices):
        target = video_folder / f"frame_{index:06d}.png"
        try:
            os.link(forward[source_index], target)
        except OSError:
            shutil.copyfile(forward[source_index], target)
        sequence.append(target)
    encode_h264(sequence, fps=fps, output_path=output / "replay.mp4")
    manifest = {
        "schema_version": 1,
        "replay": original["replay"],
        "frame_count": len(indices),
        "forward_frame_count": len(forward),
        "forward_final_frame_matches_static": True,
        "final_frame_matches_static": sequence[-1].read_bytes() == static_path.read_bytes(),
        "loop_seam_matches": sequence[-1].read_bytes() == sequence[0].read_bytes(),
        "viewport": {"width": final.width, "height": final.height},
        "export": {
            "source_manifest_sha256": hashlib.sha256(
                (source / "manifest.json").read_bytes()
            ).hexdigest(),
            "crop_xywh_requested": crop,
            "crop_ltrb_pixels": bounds,
            "reverse_speed": reverse_speed,
            "reverse_skips_final_hold": True,
            "source_frame_indices": indices,
        },
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--crop", nargs=4, type=float)
    parser.add_argument("--reverse-speed", type=int, default=0)
    args = parser.parse_args()
    export_replay(args.source, args.output, args.crop, args.reverse_speed)


if __name__ == "__main__":
    main()
