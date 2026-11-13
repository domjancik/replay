"""Browser-only parsing/timing bridge; rasterization is performed by Rust WASM."""

from dataclasses import asdict
from io import BytesIO
from zipfile import ZipFile

from rm_redraw.parsing import parse_page
from rm_redraw.pipeline import to_render_page
from rm_redraw.replay.schedule import duration_schedule, ordered_stroke_ids
from rm_redraw.web.library import inspect_archive
from rm_redraw.web.settings import validate_settings


def inspect(raw):
    result = inspect_archive(raw)
    result.pop("member_hashes", None)
    result["has_pdf"] = False
    return result


def page_bytes(raw, member):
    with ZipFile(BytesIO(raw)) as archive:
        return archive.read(member)


def info(raw, page_id):
    page = parse_page(BytesIO(raw), page_id=page_id)
    return dict(
        strokes=len(page.strokes),
        paper_size=page.paper_size,
        source_to_page_transform=page.source_to_page_transform,
        unresolved_anchors=sum(not s.effective_transform.resolved for s in page.strokes),
    )


def prepare(raw, page_id, settings):
    config = validate_settings(settings)
    parsed = parse_page(BytesIO(raw), page_id=page_id)
    if any(not stroke.effective_transform.resolved for stroke in parsed.strokes):
        raise ValueError(
            "This page needs native PDF text-anchor matching, which is not yet "
            "supported in the browser edition."
        )
    page = to_render_page(
        parsed, paper_size=config["paper_size"], source_to_page_transform=config["source_affine"]
    )
    visible = set(ordered_stroke_ids(page, config["ordering"]))
    if not visible:
        raise ValueError("Page has no visible strokes to replay")
    if not config["allow_clipping"]:
        width, height = config["paper_size"]
        if any(
            not (0 <= p.x <= width and 0 <= p.y <= height)
            for stroke in page.strokes
            if stroke.stroke_id in visible
            for p in stroke.points
        ):
            raise ValueError(
                "Visible stroke points fall outside the selected canvas. "
                "Adjust the canvas dimensions or offsets, or allow clipping."
            )
    frames = duration_schedule(
        page,
        fps=config["fps"],
        duration_seconds=config["seconds"],
        final_hold_seconds=1,
        ordering=config["ordering"],
    )
    visibility = []
    for frame in frames:
        value = asdict(frame.visibility)
        value["completed_stroke_ids"] = sorted(value["completed_stroke_ids"])
        visibility.append(value)
    return dict(
        request=dict(
            page=asdict(page),
            options=dict(viewport=dict(width=config["viewport"][0], height=config["viewport"][1])),
        ),
        frames=visibility,
        config=config,
    )
