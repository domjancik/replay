"""Reference-bound, locally reviewed anchor layouts for the replay utility."""

import hashlib
import json

from rm_redraw.replay.command import _load_text_anchor_layout


def _sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def anchor_arguments(source, page_id, pdf_page, settings):
    """Use an explicit sidecar only for its exact raw/reference/geometry binding.

    Sidecars are locally prepared evidence, never trusted from archive members.
    A failed binding must not silently fall back to an unrelated layout.
    """
    name = "anchor-layout-" + hashlib.sha256(page_id.encode("utf-8")).hexdigest() + ".json"
    path = source.with_name(name)
    if not path.exists():
        return ["--auto-text-anchors"]
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("Anchor layout sidecar exceeds 1 MiB")
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "archive_sha256": _sha256(source),
        "pdf_sha256": _sha256(source.with_name("native.pdf")),
        "page_id": page_id,
        "pdf_page": pdf_page,
        "paper_size": list(settings["paper_size"]),
        "source_affine": list(settings["source_affine"]),
    }
    if not isinstance(payload, dict) or payload.get("binding") != expected:
        raise ValueError("Anchor layout binding does not match this archive, PDF, page or geometry")
    _load_text_anchor_layout(path)
    return ["--text-anchor-layout", str(path)]
