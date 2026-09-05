from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, StreamObject

from rm_redraw.comparison.command import ComparisonError, run_comparison


def _ink_image(path: Path, *, offset: int = 0, mode: str = "RGB") -> None:
    image = Image.new(mode, (48, 36), "white")
    ImageDraw.Draw(image).line((8 + offset, 10, 32 + offset, 24), fill="black", width=3)
    image.save(path)


def _text_and_ink_pdf(path: Path) -> None:
    """Build a deterministic native-like PDF with selectable text and vector ink."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=48, height=36)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {
                    NameObject("/F1"): DictionaryObject(
                        {
                            NameObject("/Type"): NameObject("/Font"),
                            NameObject("/Subtype"): NameObject("/Type1"),
                            NameObject("/BaseFont"): NameObject("/Helvetica"),
                        }
                    )
                }
            )
        }
    )
    content = StreamObject()
    content.set_data(b"BT /F1 20 Tf 2 17 Td (A) Tj ET 0 0 0 RG 3 w 5 5 m 42 5 l S\n")
    page.replace_contents(content)
    with path.open("wb") as destination:
        writer.write(destination)


def test_writes_required_artifacts_and_metric_provenance(tmp_path: Path) -> None:
    native = tmp_path / "native.png"
    candidate = tmp_path / "candidate.png"
    output = tmp_path / "comparison"
    _ink_image(native)
    _ink_image(candidate, offset=2)

    result = run_comparison(candidate, native_png=native, output_directory=output)

    assert result.output_directory == output
    assert {path.name for path in output.iterdir()} == {
        "native.png",
        "ours.png",
        "absolute-diff.png",
        "high-gain-diff.png",
        "overlay.png",
        "metrics.json",
    }
    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["schema_version"] == 1
    assert metrics["inputs"]["candidate"]["sha256"]
    assert metrics["inputs"]["native"]["sha256"]
    assert metrics["rasterization"] == {"source": "native-png"}
    assert metrics["images"]["dimensions"] == [48, 36]
    assert metrics["images"]["mode"] == "RGB"
    assert metrics["roi"]["padding_px"] == 12
    assert metrics["definitions"]["ssim"]
    assert metrics["metrics"]["global"]["mae"] > 0
    assert metrics["metrics"]["ink_roi"]["rmse"] > 0
    assert metrics["metrics"]["edge_geometry"]["symmetric_mean_distance_px"] > 0
    assert set(metrics["outputs"]) == {
        "native.png",
        "ours.png",
        "absolute-diff.png",
        "high-gain-diff.png",
        "overlay.png",
    }


def test_rejects_existing_output_directory(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    _ink_image(image)
    output = tmp_path / "already-exists"
    output.mkdir()

    with pytest.raises(ComparisonError, match="new output directory"):
        run_comparison(image, native_png=image, output_directory=output)


def test_rejects_dimension_and_colour_mode_mismatches(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.png"
    native = tmp_path / "native.png"
    _ink_image(candidate)
    Image.new("RGB", (49, 36), "white").save(native)

    with pytest.raises(ComparisonError, match="dimensions differ"):
        run_comparison(candidate, native_png=native, output_directory=tmp_path / "size")

    _ink_image(native, mode="RGBA")
    with pytest.raises(ComparisonError, match="colour modes differ"):
        run_comparison(candidate, native_png=native, output_directory=tmp_path / "mode")


def test_rasterizes_selected_native_pdf_page_to_candidate_dimensions(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.png"
    native_pdf = tmp_path / "native.pdf"
    _ink_image(candidate)
    Image.new("RGB", (96, 72), "white").save(native_pdf, "PDF")

    run_comparison(candidate, native_pdf=native_pdf, output_directory=tmp_path / "pdf-report")

    metrics = json.loads((tmp_path / "pdf-report" / "metrics.json").read_text(encoding="utf-8"))
    assert Image.open(tmp_path / "pdf-report" / "native.png").size == (48, 36)
    assert metrics["rasterization"]["source"] == "native-pdf"
    assert metrics["rasterization"]["settings"]["scale_to_x"] == 48
    assert metrics["rasterization"]["settings"]["scale_to_y"] == 36


def test_native_pdf_ink_only_filters_text_and_records_operator_provenance(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.png"
    native_pdf = tmp_path / "native.pdf"
    Image.new("RGB", (48, 36), "white").save(candidate)
    _text_and_ink_pdf(native_pdf)

    run_comparison(
        candidate,
        native_pdf=native_pdf,
        ink_only=True,
        output_directory=tmp_path / "ink-only-report",
    )

    output = tmp_path / "ink-only-report"
    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
    native = np.asarray(Image.open(output / "native.png"))
    assert metrics["comparison_scope"] == "ink-only-native-pdf"
    assert metrics["native_content_filter"] == {
        "direct_text_painting_operators": 1,
        "removed_text_operators": 5,
        "scope": "direct-page-content-only",
        "strategy": "remove-text-objects-from-native-pdf-content-stream",
        "unfiltered_content": ["form-xobjects", "images", "annotations"],
    }
    assert not (native[:20, :20, :3] < 245).any(), "the typed glyph must not survive filtering"
    assert (native[28:, :, :3] < 245).any(), "the vector ink path must remain"


def test_tiny_images_emit_standard_json_with_unavailable_ssim_as_null(tmp_path: Path) -> None:
    native = tmp_path / "native.png"
    candidate = tmp_path / "candidate.png"
    Image.new("RGB", (6, 6), "white").save(native)
    Image.new("RGB", (6, 6), "white").save(candidate)

    run_comparison(candidate, native_png=native, output_directory=tmp_path / "tiny-report")

    report = (tmp_path / "tiny-report" / "metrics.json").read_text(encoding="utf-8")
    metrics = json.loads(report)
    assert "NaN" not in report
    assert metrics["metrics"]["global"]["ssim"] is None
    assert metrics["metrics"]["ink_roi"]["ssim"] is None
