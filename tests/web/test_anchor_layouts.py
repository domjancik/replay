import hashlib
import json

import pytest

from rm_redraw.web.anchor_layouts import anchor_arguments


def setup_layout(tmp_path):
    source = tmp_path / "document.rmdoc"
    source.write_bytes(b"raw archive")
    pdf = tmp_path / "native.pdf"
    pdf.write_bytes(b"paired pdf")
    settings = {"paper_size": (1404, 1872), "source_affine": (1, 0, 0, 1, 702, 0)}
    payload = {
        "schema_version": 1,
        "offsets": {"1:17": 63.0},
        "evidence": "Measured against the paired reference at source resolution.",
        "binding": {
            "archive_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            "page_id": "page-one",
            "pdf_page": 1,
            **settings,
        },
    }
    path = tmp_path / ("anchor-layout-" + hashlib.sha256(b"page-one").hexdigest() + ".json")
    path.write_text(json.dumps(payload))
    return source, settings, payload, path


def test_reference_bound_layout_replaces_automatic_matching(tmp_path):
    source, settings, _payload, path = setup_layout(tmp_path)
    assert anchor_arguments(source, "page-one", 1, settings) == ["--text-anchor-layout", str(path)]
    assert anchor_arguments(source, "other-page", 2, settings) == ["--auto-text-anchors"]


@pytest.mark.parametrize(
    "field", ["archive_sha256", "pdf_sha256", "page_id", "pdf_page", "paper_size", "source_affine"]
)
def test_stale_or_mismatched_layout_fails_closed(tmp_path, field):
    source, settings, payload, path = setup_layout(tmp_path)
    payload["binding"][field] = "wrong"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="binding"):
        anchor_arguments(source, "page-one", 1, settings)


def test_invalid_offsets_are_rejected_before_launch(tmp_path):
    source, settings, payload, path = setup_layout(tmp_path)
    payload["offsets"]["1:17"] = "bad"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="text-anchor-layout"):
        anchor_arguments(source, "page-one", 1, settings)
