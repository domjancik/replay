"""Emit deterministic Pillow reference cases beneath the ignored artifacts tree."""

import argparse
import hashlib
import json
from dataclasses import asdict, replace
from io import BytesIO
from pathlib import Path
from time import perf_counter
from zipfile import ZipFile

import PIL
from rmscene.scene_items import Pen

from rm_redraw.parsing import parse_page
from rm_redraw.pipeline import to_render_page
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
from rm_redraw.replay.schedule import duration_schedule

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts" / "rust-renderer"
TRANSLUCENT = (231, 217, 194, 103)
INK_GROUP = (NormalizedGroup("ink"),)


def point(x, y, pressure=160.0, width=38.0, speed=19.0, direction=17.0):
    return NormalizedPoint(x, y, pressure, speed, direction, width)


def stroke(id_, code, points, *, group="ink", rgba=(23, 72, 133, 211), name=None):
    return NormalizedStroke(id_, group, rgba, 3.25, tuple(points), code, name)


def page(id_, strokes, groups=INK_GROUP, size=(96.0, 72.0)):
    strokes = tuple(strokes)
    return NormalizedPage(
        id_,
        size,
        groups,
        strokes,
        tuple(group.group_id for group in groups),
        tuple(stroke.stroke_id for stroke in strokes),
        "crdt-order",
        "Synthetic reference",
    )


def visibility(completed=(), active=None, progress=0.0):
    return VisibilityState(frozenset(completed), active, progress)


def synthetic_cases():
    options = RenderOptions()
    colored = RenderOptions(background=TRANSLUCENT)
    small = RenderOptions(viewport=Viewport(65, 49), background=TRANSLUCENT)
    varying = (
        point(-4.75, 8.25, 32, 20, 12, 248),
        point(21.375, 28.5, 167, 44, 98, 7),
        point(57.5, 13.75, 232, 71, 44, 108),
        point(99.125, 54.75, 103, 39, 27, 169),
    )
    for tool in [*Pen, 999]:
        code = int(tool)
        name = tool.name if isinstance(tool, Pen) else None
        drawing = page(f"tool-{code}", [stroke("1:1", code, varying, name=name)])
        yield f"tool-{code}-source", drawing, options, None
        yield f"tool-{code}-anisotropic", drawing, small, visibility(active="1:1", progress=0.69)

    for code in (0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 13, 14, 15, 16, 17, 18, 21, 23):
        taps = page(
            f"taps-{code}",
            [
                stroke("single", code, [point(10.125, 13.75)]),
                stroke("duplicate", code, [point(30.25, 13.5)] * 2),
                stroke("epsilon", code, [point(50.25, 13.75), point(50.26, 13.75)]),
                stroke("short", code, [point(69.75, 13.125), point(70.25, 13.625)]),
                stroke("missing", code, [point(14.25, 32, width=None), point(33, 46, width=None)]),
            ],
        )
        yield f"taps-{code}", taps, colored, None

    groups = NormalizedGroup("ink"), NormalizedGroup("upper"), NormalizedGroup("hidden", False)
    mixed = page(
        "mixed",
        [
            stroke("lower", 17, [point(5, 19), point(78, 55)], rgba=(57, 35, 123, 210)),
            stroke("upper-pencil", 14, varying, group="upper", rgba=(29, 48, 84, 209)),
            stroke("highlight", 18, [point(5, 55), point(84, 26)], rgba=(254, 252, 100, 159)),
            stroke(
                "highlight-overlap", 18, [point(4, 46), point(80, 37)], rgba=(255, 128, 157, 151)
            ),
            stroke("erase", 6, [point(28.2, 7.75), point(46.7, 40.4, width=53), point(63, 70)]),
            stroke("later", 2, [point(15, 43), point(87, 41)], rgba=(87, 91, 27, 223)),
            stroke(
                "brush", 12, [point(65, 8), point(44, 59)], group="upper", rgba=(167, 40, 68, 199)
            ),
            stroke("hidden", 13, varying, group="hidden"),
        ],
        groups,
    )
    for label, config in [
        ("source", colored),
        ("box", small),
        ("wide-box", replace(small, viewport=Viewport(101, 47))),
    ]:
        yield f"mixed-{label}-static", mixed, config, None
        yield f"mixed-{label}-empty", mixed, config, visibility()
        yield (
            f"mixed-{label}-erase-prefix",
            mixed,
            config,
            visibility(
                ("lower", "highlight", "highlight-overlap"),
                "erase",
                0.46,
            ),
        )
        yield (
            f"mixed-{label}-nonprefix",
            mixed,
            config,
            visibility(("highlight", "brush"), "lower", 0.31),
        )
        yield f"mixed-{label}-reverse", mixed, config, visibility(("lower",), "highlight", 0.15)
        yield f"mixed-{label}-all", mixed, config, visibility(mixed.replay_order)
    hidden_texture = replace(
        mixed, groups=(NormalizedGroup("ink"), NormalizedGroup("upper", False), groups[-1])
    )
    yield "mixed-hidden-texture", hidden_texture, small, None

    replay_options = RenderOptions(viewport=Viewport(72, 54))
    frames = duration_schedule(
        mixed,
        fps=12,
        duration_seconds=2,
        initial_pause_seconds=0.25,
        final_hold_seconds=0.125,
        ordering="entry",
    )
    for frame in frames:
        yield f"replay-{frame.index:03}", mixed, replay_options, frame.visibility
    yield "replay-static", mixed, replay_options, None

    for code in (13, 14):
        test = page(
            f"boundary-{code}",
            [
                stroke("border", code, varying, rgba=(18, 109, 65, 172)),
                stroke("repeat", code, varying, rgba=(18, 109, 65, 172)),
            ],
        )
        for boundary in (False, True):
            config = replace(small, pencil_boundary=boundary)
            label = "sparse" if boundary else "app"
            yield f"pencil-{code}-{label}-static", test, config, None
            yield (
                f"pencil-{code}-{label}-active",
                test,
                config,
                visibility(("border",), "repeat", 0.51),
            )

    fallback = page(
        "fallback",
        [
            stroke("unknown", None, [point(-8, 14), point(21, 20), point(45, 49), point(79, 8)]),
            stroke("stationary", None, [point(8.25, 16.5)], rgba=(228, 61, 49, 91)),
            stroke("name-only", None, [point(19, 8), point(45, 42)], name="FINELINER_2"),
        ],
    )
    yield "fallback-and-name-dispatch", fallback, colored, None


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def write_case(target, renderer, name, drawing, options, state, *, private=False):
    request = {
        "page": asdict(drawing),
        "options": {
            "viewport": asdict(options.viewport) if options.viewport else None,
            "background": options.background,
            "pencil_boundary": options.pencil_boundary,
        },
        "visibility": None
        if state is None
        else {
            "completed_stroke_ids": sorted(state.completed_stroke_ids),
            "active_stroke_id": state.active_stroke_id,
            "active_progress": state.active_progress,
        },
    }
    start = perf_counter()
    image = (
        renderer.render_static(drawing, options)
        if state is None
        else renderer.render(drawing, options, state)
    )
    elapsed = perf_counter() - start
    data = image.tobytes()
    json_name, rgba_name = f"{name}.json", f"{name}.rgba"
    (target / json_name).write_text(
        json.dumps(request, separators=(",", ":"), allow_nan=False), encoding="utf-8"
    )
    (target / rgba_name).write_bytes(data)
    return {
        "id": name,
        "request": json_name,
        "rgba": rgba_name,
        "width": image.width,
        "height": image.height,
        "sha256": sha256(data),
        "python_seconds": elapsed,
        "private": private,
    }


def write_manifest(target, rows):
    (target / "cases.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "pillow": PIL.__version__,
                "cases": rows,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def natural_case(args, renderer):
    with ZipFile(args.natural_archive) as archive:
        raw = archive.read(args.natural_member)
    drawing = to_render_page(
        parse_page(BytesIO(raw), page_id="natural-portrait"),
        paper_size=(1404, 1872),
        source_to_page_transform=(1, 0, 0, 1, 702, 0),
    )
    target = ARTIFACTS / "private"
    target.mkdir(parents=True, exist_ok=True)
    options = RenderOptions(viewport=Viewport(702, 936))
    result = write_case(target, renderer, "natural-portrait", drawing, options, None, private=True)
    result["source_sha256"] = sha256(raw)
    result["stroke_count"] = len(drawing.strokes)
    write_manifest(target, [result])
    print(f"{len(drawing.strokes)}-stroke natural case written to {target}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--natural-archive", type=Path)
    parser.add_argument("--natural-member")
    args = parser.parse_args()
    if bool(args.natural_archive) != bool(args.natural_member):
        parser.error("Provide --natural-archive and --natural-member together")
    target = ARTIFACTS / "synthetic"
    target.mkdir(parents=True, exist_ok=True)
    renderer = PillowRenderer()
    rows = [write_case(target, renderer, *case) for case in synthetic_cases()]
    write_manifest(target, rows)
    print(f"{len(rows)} synthetic cases written to {target}")
    if args.natural_archive:
        natural_case(args, renderer)


if __name__ == "__main__":
    main()
