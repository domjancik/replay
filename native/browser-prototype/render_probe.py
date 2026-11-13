"""Run the existing parser, schedule and rasterizer on a synthetic v6 page."""

import json
import sys
from io import BytesIO
from pathlib import Path
from time import perf_counter
from zipfile import ZipFile

import numpy
from PIL import __version__ as pillow_version

from rm_redraw.parsing import parse_page
from rm_redraw.pipeline import to_render_page
from rm_redraw.rendering import PillowRenderer, RenderOptions, Viewport
from rm_redraw.replay.schedule import duration_schedule


def render_probe(page_archive, output):
    """Return a manifest and serialize the replay followed by a static frame."""
    start = perf_counter()
    with ZipFile(BytesIO(page_archive)) as archive:
        parsed = parse_page(BytesIO(archive.read("page.rm")), page_id="synthetic")
    page = to_render_page(parsed, source_to_page_transform=(1, 0, 0, 1, 0, 0))
    parse_ms = (perf_counter() - start) * 1000
    options = RenderOptions(viewport=Viewport(96, 72))
    frames = duration_schedule(
        page,
        fps=12,
        duration_seconds=2,
        initial_pause_seconds=0.25,
        final_hold_seconds=0.125,
        ordering="entry",
    )
    renderer = PillowRenderer()
    first = last = b""
    changed_frames = 0
    render_start = perf_counter()
    for frame in frames:
        previous = last
        last = renderer.render(page, options, frame.visibility).tobytes()
        if frame.index == 0:
            first = last
        changed_frames += bool(previous and last != previous)
        output.write(last)
    static = renderer.render_static(page, options).tobytes()
    output.write(static)
    assert first != static and last == static
    return {
        "python": sys.version.split()[0],
        "numpy": numpy.__version__,
        "pillow": pillow_version,
        "viewport": [options.viewport.width, options.viewport.height],
        "paperSize": list(page.paper_size),
        "layers": len(page.groups),
        "tools": sorted(stroke.tool_code for stroke in page.strokes),
        "fps": 12,
        "frameCount": len(frames),
        "changedFrames": changed_frames,
        "finalEqualsStatic": last == static,
        "parseMs": round(parse_ms, 3),
        "renderMs": round((perf_counter() - render_start) * 1000, 3),
    }


def main(directory):
    with (directory / "expected.rgba").open("wb") as output:
        manifest = render_probe((directory / "synthetic.rmdoc").read_bytes(), output)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
