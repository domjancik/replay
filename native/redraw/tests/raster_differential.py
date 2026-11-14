"""Generate 700 seeded Pillow references and compare a native Rust renderer.

Run from the repository root with the project's Python and a release renderer
shared library as the sole argument. The generated request JSON and RGBA
hashes go to the ignored artifacts/rust-renderer-raster directory.
"""

import ctypes
import json
import sys
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from random import Random

from rm_redraw.rendering.pillow import PillowRenderer
from rm_redraw.rendering.types import (
    NormalizedGroup,
    NormalizedPage,
    NormalizedPoint,
    NormalizedStroke,
    RenderOptions,
    Viewport,
    VisibilityState,
)

TOOLS = (6, 15, 16, 17, 18, 21, 23)
VIEWPORT = Viewport(48, 34)


def request_and_reference(random, code, case):
    coordinates = [
        (random.randrange(-60, 435) / 8, random.randrange(-65, 315) / 8)
        for _ in range(1 + random.randrange(12))
    ]
    if case % 4 == 0 and len(coordinates) > 2:
        coordinates[1] = coordinates[0]
    widths = [random.choice((None, 0.0, 4.0, 12.0, 30.0, 42.0, 73.0, 94.0)) for _ in coordinates]
    if case % 2 == 0:
        widths = [widths[0]] * len(coordinates)
    points = tuple(
        NormalizedPoint(
            x,
            y,
            random.randrange(256),
            random.choice((None, 14.0, 49.0, 132.0)),
            random.randrange(255),
            width,
        )
        for (x, y), width in zip(coordinates, widths, strict=True)
    )
    color = tuple(random.randrange(256) for _ in range(4))
    test_stroke = NormalizedStroke(
        "sample", "ink", color, random.randrange(1, 20) / 2, points, code
    )
    base_stroke = NormalizedStroke(
        "base",
        "ink",
        (19, 43, 77, 223),
        25.0,
        (NormalizedPoint(1, 17), NormalizedPoint(47, 17)),
        23,
    )
    sx, sy = random.choice(((1.0, 1.0), (1.1, 0.9), (0.67, 1.25), (1.5, 2.4)))
    page = NormalizedPage(
        "raster",
        (VIEWPORT.width / sx, VIEWPORT.height / sy),
        (NormalizedGroup("ink"),),
        (base_stroke, test_stroke),
        ("ink",),
        ("base", "sample"),
        "scene-order",
        "synthetic",
    )
    options = RenderOptions(viewport=VIEWPORT, background=(62, 13, 91, 151))
    progress = random.choice((0.0, 0.03, 0.318, 0.5, 0.75, 0.939, 1.0))
    visibility = VisibilityState(frozenset(("base",)), "sample", progress)
    expected = PillowRenderer().render(page, options, visibility).tobytes()
    request = json.dumps(
        {
            "page": asdict(page),
            "options": asdict(options),
            "visibility": {
                "completed_stroke_ids": ["base"],
                "active_stroke_id": "sample",
                "active_progress": progress,
            },
        }
    )
    return request, expected


def native_renderer(library_path):
    library = ctypes.CDLL(str(library_path.resolve()))
    size = ctypes.c_size_t
    pointer = ctypes.c_void_p
    api = {}
    for name, arguments, result in (
        ("alloc", [size], pointer),
        ("free", [pointer, size], None),
        ("render_json", [pointer, size], ctypes.c_uint32),
        ("error_ptr", [], pointer),
        ("error_len", [], size),
        ("output_ptr", [], pointer),
        ("output_len", [], size),
    ):
        method = getattr(library, f"rm_renderer_{name}")
        method.argtypes = arguments
        method.restype = result
        api[name] = method

    def render(request):
        data = request.encode()
        buffer = api["alloc"](len(data))
        if not buffer:
            raise RuntimeError("renderer could not allocate the request")
        try:
            ctypes.memmove(buffer, data, len(data))
            if api["render_json"](buffer, len(data)):
                raise RuntimeError(
                    ctypes.string_at(api["error_ptr"](), api["error_len"]()).decode()
                )
            return ctypes.string_at(api["output_ptr"](), api["output_len"]())
        finally:
            api["free"](buffer, len(data))

    return render


def main(library_path):
    random = Random(887633)
    render = native_renderer(library_path)
    output = Path(__file__).resolve().parents[3] / "artifacts/rust-renderer-raster"
    output.mkdir(parents=True, exist_ok=True)
    cases = []
    mismatches = []
    for code in TOOLS:
        for case in range(100):
            request, expected = request_and_reference(random, code, case)
            cases.append((code, case, request, sha256(expected).hexdigest()))
            actual = render(request)
            if actual != expected:
                mismatches.append((code, case))
                (output / f"case-{code}-{case}.expected.rgba").write_bytes(expected)
                (output / f"case-{code}-{case}.actual.rgba").write_bytes(actual)
    (output / "randomized.json").write_text(json.dumps(cases), encoding="utf-8")
    print(f"{len(cases)} synthetic cases, {len(mismatches)} native differences")
    if mismatches:
        raise SystemExit(f"Differences for tool/case {mismatches}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
