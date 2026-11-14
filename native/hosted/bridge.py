"""Browser-only parsing/timing bridge; rasterization is performed by Rust WASM."""

from dataclasses import asdict
from io import BytesIO
from zipfile import ZipFile

from rm_redraw.parsing import CrdtIdentifier, TextAnchorLayout, parse_page
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


def prepare(raw, page_id, settings, anchor_result=None, native_timing=False):
    config = validate_settings(settings)
    layout = None
    if anchor_result:
        plan = anchor_templates(raw, page_id, settings)
        offsets = resolve_anchor_fits(plan, anchor_result["fits"])
        layout = TextAnchorLayout(
            {CrdtIdentifier(*map(int, key.split(":"))): value for key, value in offsets.items()},
            anchor_result["evidence"],
        )
    parsed = parse_page(BytesIO(raw), page_id=page_id, text_anchor_layout=layout)
    if any(not stroke.effective_transform.resolved for stroke in parsed.strokes):
        raise ValueError(
            "This page needs native PDF text-anchor matching. Attach the matching native PDF."
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
    visibility = []
    if not native_timing:
        frames = duration_schedule(
            page,
            fps=config["fps"],
            duration_seconds=config["seconds"],
            final_hold_seconds=1,
            ordering=config["ordering"],
        )
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


def anchor_templates(raw, page_id, settings):
    config = validate_settings(settings)
    page = parse_page(BytesIO(raw), page_id=page_id)
    if not any(not s.effective_transform.resolved for s in page.strokes):
        return None
    root = next(
        (
            b
            for b in page.diagnostics.blocks
            if b.block_name == "RootTextBlock" and not b.unreadable
        ),
        None,
    )
    if root is None:
        raise ValueError("Missing root text geometry for native anchor matching")
    root_y = float(root.fields["value"]["pos_y"])
    groups = {g.node_id: g for g in page.groups}
    templates = []
    for group in page.groups:
        if not group.local_transform.anchor_ids:
            continue
        anchor_type = group.extra.get("anchor_type", {}).get("value")
        if anchor_type != 2:
            if not group.effective_transform.resolved:
                raise ValueError("Unsupported native text-anchor type")
            continue
        parent_id = group.parent_id
        visited = {group.node_id}
        while parent_id in groups:
            ancestor = groups[parent_id]
            if parent_id in visited or not ancestor.effective_transform.resolved:
                raise ValueError("unsupported-unresolved-ancestor")
            visited.add(parent_id)
            parent_id = ancestor.parent_id
        local = group.local_transform.matrix
        effective = group.effective_transform.matrix
        if local[:4] != (1, 0, 0, 1) or effective[:4] != (1, 0, 0, 1):
            raise ValueError("unsupported-nontranslation-group-transform")
        strokes = [
            [[p.x, p.y] for p in stroke.points]
            for stroke in page.strokes
            if stroke.parent_id == group.node_id and len(stroke.points) >= 2
        ]
        if not strokes:
            raise ValueError(f"Group {group.node_id}: unsupported-no-direct-stroke-template")
        templates.append(
            dict(
                group_id=str(group.node_id),
                anchor_id=str(group.local_transform.anchor_ids[0]),
                parent_y=effective[5] - local[5],
                strokes=strokes,
                expected_x=config["source_affine"][4] + effective[4],
            )
        )
    if not templates:
        raise ValueError("Unresolved page has no supported native anchor templates")
    return dict(root_y=root_y, page_y=config["source_affine"][5], templates=templates)


def resolve_anchor_fits(plan, fits):
    if len(fits) != len(plan["templates"]):
        raise ValueError("Native anchor result count mismatch")
    offsets = {}
    for template, fit in zip(plan["templates"], fits, strict=True):
        if not fit["accepted"]:
            raise ValueError(f"Group {template['group_id']}: {fit['reason']}")
        offset = (
            fit["best_candidate"]["translation_y"]
            - plan["page_y"]
            - template["parent_y"]
            - plan["root_y"]
        )
        key = template["anchor_id"]
        if key in offsets and offsets[key] != offset:
            raise ValueError("conflicting-shared-anchor-offsets")
        offsets[key] = offset
    return offsets
