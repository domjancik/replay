from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from pypdf import PdfWriter
from pypdf.generic import StreamObject

from rm_redraw.comparison.anchor_fit import fit_anchor_template, native_vector_ink_mask


def _mask_with_shape(*translations: tuple[int, int]) -> np.ndarray:
    image = Image.new("1", (180, 180), 0)
    draw = ImageDraw.Draw(image)
    for tx, ty in translations:
        draw.line(((tx, ty), (tx, ty + 24), (tx + 20, ty + 24)), fill=1, width=3)
    return np.asarray(image, dtype=bool)


def _vector_pdf(path: Path) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=180, height=180)
    content = StreamObject()
    content.set_data(b"1 0 0 -1 0 180 cm 70 90 m 70 114 l 90 114 l 90 117 l 67 117 l 67 90 l f\n")
    page.replace_contents(content)
    with path.open("wb") as destination:
        writer.write(destination)


def test_native_vector_mask_uses_native_source_coordinate_scale(tmp_path: Path) -> None:
    pdf = tmp_path / "native.pdf"
    _vector_pdf(pdf)

    mask = native_vector_ink_mask(pdf, page=1, canvas=(180, 180))

    assert mask.shape == (180, 180)
    assert mask[100, 70]
    assert mask[115, 80]


def test_anchor_fit_accepts_one_unique_native_translation() -> None:
    points = np.asarray(((0, 0), (0, 8), (0, 16), (0, 24), (10, 24), (20, 24)))

    fit = fit_anchor_template(_mask_with_shape((70, 90)), points, expected_x=70)

    assert fit.accepted is True
    assert abs(fit.translation_x - 70) <= 0.25
    assert abs(fit.translation_y - 90) <= 0.25
    assert fit.fraction_within_2px >= 0.95


def test_anchor_fit_rejects_two_equally_good_native_translations() -> None:
    points = np.asarray(((0, 0), (0, 8), (0, 16), (0, 24), (10, 24), (20, 24)))

    fit = fit_anchor_template(_mask_with_shape((70, 40), (70, 110)), points, expected_x=70)

    assert fit.accepted is False
    assert fit.reason == "ambiguous-native-match"
    assert fit.second_candidate is not None


def test_anchor_fit_rejects_incidental_low_overlap() -> None:
    points = np.asarray(((0, 0), (0, 8), (0, 16), (0, 24), (10, 24), (20, 24)))
    image = Image.new("1", (180, 180), 0)
    ImageDraw.Draw(image).point((70, 90), fill=1)

    fit = fit_anchor_template(np.asarray(image, dtype=bool), points, expected_x=70)

    assert fit.accepted is False
    assert fit.reason == "insufficient-native-overlap"


def test_anchor_fit_rejects_template_embedded_in_unrelated_filled_region() -> None:
    points = np.asarray(((0, 0), (0, 24), (20, 24)))
    image = Image.new("1", (180, 180), 0)
    ImageDraw.Draw(image).rectangle((66, 72, 102, 126), fill=1)

    fit = fit_anchor_template(np.asarray(image, dtype=bool), points, expected_x=70)

    assert fit.accepted is False
    assert fit.reason == "inconsistent-native-shape"


def test_anchor_fit_rejects_wrong_native_shape_at_expected_x() -> None:
    points = np.asarray(((0, 0), (0, 24), (20, 24)))
    image = Image.new("1", (180, 180), 0)
    ImageDraw.Draw(image).line(((70, 90), (70, 130)), fill=1, width=3)

    fit = fit_anchor_template(np.asarray(image, dtype=bool), points, expected_x=70)

    assert fit.accepted is False


def test_native_mask_honors_transform_stack_and_erasing(tmp_path: Path) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=90, height=90)
    content = StreamObject()
    content.set_data(
        b"0.5 0 0 -0.5 0 90 cm "
        b"q 1 0 0 1 40 60 cm 0 g 0 0 30 30 re f "
        b"1 g 10 10 10 10 re f Q "
        b"0 g 100 100 10 10 re f"
    )
    page.replace_contents(content)
    pdf = tmp_path / "transformed.pdf"
    with pdf.open("wb") as output:
        writer.write(output)
    mask = native_vector_ink_mask(pdf, page=1, canvas=(180, 180))
    assert mask[65, 45]
    assert not mask[75, 55]
    assert mask[105, 105]
    assert not mask[125, 85]


def test_native_mask_respects_evenodd_holes_curves_and_clipping(tmp_path: Path) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=180, height=180)
    content = StreamObject()
    content.set_data(
        b"1 0 0 -1 0 180 cm "
        b"q 10 10 50 50 re W n 0 0 90 90 re 20 20 10 10 re f* Q "
        b"100 100 m 100 140 140 140 140 100 c h f"
    )
    page.replace_contents(content)
    pdf = tmp_path / "curves.pdf"
    with pdf.open("wb") as output:
        writer.write(output)
    mask = native_vector_ink_mask(pdf, page=1, canvas=(180, 180))
    assert mask[15, 15]
    assert not mask[25, 25]
    assert not mask[70, 70]
    assert mask[115, 120]


def test_native_mask_rejects_unfiltered_xobjects(tmp_path: Path) -> None:
    import pytest

    writer = PdfWriter()
    page = writer.add_blank_page(width=180, height=180)
    content = StreamObject()
    content.set_data(b"1 0 0 -1 0 180 cm /Unknown Do 10 10 20 20 re f")
    page.replace_contents(content)
    pdf = tmp_path / "xobject.pdf"
    with pdf.open("wb") as output:
        writer.write(output)
    with pytest.raises(ValueError, match="XObject"):
        native_vector_ink_mask(pdf, page=1, canvas=(180, 180))


def test_paired_fit_derives_layout_from_pdf_without_manual_offsets(tmp_path: Path) -> None:
    from dataclasses import replace

    from rm_redraw.comparison.anchor_fit import derive_paired_text_anchor_layout
    from rm_redraw.parsing import CrdtIdentifier, parse_page
    from tests.parsing.test_text_anchor_layout import _anchored_page

    page = parse_page(_anchored_page(), page_id="synthetic")
    stroke = page.strokes[0]
    page = replace(
        page,
        strokes=(
            replace(
                stroke,
                points=tuple(
                    replace(stroke.points[0], x=x, y=y) for x, y in ((0, 0), (0, 30), (40, 30))
                ),
            ),
        ),
    )
    writer = PdfWriter()
    native = writer.add_blank_page(width=1200, height=800)
    content = StreamObject()
    content.set_data(b"1 0 0 -1 0 800 cm 3 w 1000 500 m 1000 530 l 1040 530 l S")
    native.replace_contents(content)
    pdf = tmp_path / "pair.pdf"
    with pdf.open("wb") as output:
        writer.write(output)
    fitted = derive_paired_text_anchor_layout(
        page,
        pdf,
        pdf_page=1,
        canvas=(1200, 800),
        source_to_page_transform=(1, 0, 0, 1, 600, 0),
    )
    assert fitted.layout is not None
    assert abs(fitted.layout.offsets[CrdtIdentifier(1, 17)] - 266) <= 1
    assert "raster template match" in fitted.layout.evidence
    assert all(decision.accepted for decision in fitted.decisions)


def test_paired_fit_without_applicable_anchors_is_noop(tmp_path: Path) -> None:
    from dataclasses import replace

    from rm_redraw.comparison.anchor_fit import derive_paired_text_anchor_layout
    from rm_redraw.parsing import parse_page
    from tests.parsing.test_text_anchor_layout import _anchored_page

    page = replace(parse_page(_anchored_page(), page_id="synthetic"), groups=())
    result = derive_paired_text_anchor_layout(
        page,
        tmp_path / "not-needed.pdf",
        pdf_page=1,
        canvas=(1200, 800),
        source_to_page_transform=(1, 0, 0, 1, 600, 0),
    )
    assert result.layout is None
    assert result.decisions == ()


def test_native_mask_rejects_text_clipping_and_annotations(tmp_path: Path) -> None:
    import pytest
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject

    for kind in ("text-clipping", "annotations"):
        writer = PdfWriter()
        page = writer.add_blank_page(width=180, height=180)
        content = StreamObject()
        content.set_data(
            b"1 0 0 -1 0 180 cm 0 0 30 30 re f"
            + (b" BT 7 Tr ET" if kind == "text-clipping" else b"")
        )
        page.replace_contents(content)
        if kind == "annotations":
            page[NameObject("/Annots")] = ArrayObject([DictionaryObject()])
        pdf = tmp_path / f"{kind}.pdf"
        with pdf.open("wb") as output:
            writer.write(output)
        with pytest.raises(ValueError, match="unsupported"):
            native_vector_ink_mask(pdf, page=1, canvas=(180, 180))


def test_native_mask_accepts_empty_indirect_annotations(tmp_path: Path) -> None:
    from pypdf.generic import ArrayObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=180, height=180)
    page[NameObject("/Annots")] = writer._add_object(ArrayObject())
    content = StreamObject()
    content.set_data(b"1 0 0 -1 0 180 cm 10 10 20 20 re f")
    page.replace_contents(content)
    pdf = tmp_path / "empty-annots.pdf"
    with pdf.open("wb") as output:
        writer.write(output)
    assert native_vector_ink_mask(pdf, page=1, canvas=(180, 180))[20, 20]


def _two_anchor_groups(tmp_path: Path):
    from dataclasses import replace

    from rm_redraw.parsing import parse_page
    from tests.parsing.test_text_anchor_layout import ANCHOR_ID, _anchored_page

    page = parse_page(_anchored_page(anchors=(ANCHOR_ID, ANCHOR_ID)), page_id="shared-anchor")
    anchored = [g for g in page.groups if g.local_transform.anchor_ids]
    second = anchored[1]
    second = replace(
        second,
        local_transform=replace(second.local_transform, matrix=(1, 0, 0, 1, 100, 0)),
        effective_transform=replace(second.effective_transform, matrix=(1, 0, 0, 1, 100, 0)),
    )
    page = replace(
        page,
        groups=tuple(second if g.node_id == second.node_id else g for g in page.groups),
        strokes=tuple(
            replace(
                s,
                points=tuple(
                    replace(s.points[0], x=x, y=y) for x, y in ((0, 0), (0, 30), (40, 30))
                ),
            )
            for s in page.strokes
        ),
    )
    writer = PdfWriter()
    native = writer.add_blank_page(width=1200, height=800)
    content = StreamObject()
    content.set_data(
        b"1 0 0 -1 0 800 cm 3 w 1000 500 m 1000 530 l 1040 530 l S 700 600 m 700 630 l 740 630 l S"
    )
    native.replace_contents(content)
    pdf = tmp_path / "two-groups.pdf"
    with pdf.open("wb") as output:
        writer.write(output)
    return page, pdf, anchored[0], second


def test_conflicting_shared_anchor_offsets_are_all_rejected(tmp_path: Path) -> None:
    from rm_redraw.comparison.anchor_fit import derive_paired_text_anchor_layout

    page, pdf, _first, _second = _two_anchor_groups(tmp_path)
    result = derive_paired_text_anchor_layout(
        page, pdf, pdf_page=1, canvas=(1200, 800), source_to_page_transform=(1, 0, 0, 1, 600, 0)
    )
    assert result.layout is None
    assert len(result.decisions) == 2
    assert all(
        not d.accepted and d.reason == "conflicting-shared-anchor-offsets" for d in result.decisions
    )


def test_unresolved_ancestor_is_not_treated_as_known_translation(tmp_path: Path) -> None:
    from dataclasses import replace

    from rm_redraw.comparison.anchor_fit import derive_paired_text_anchor_layout

    page, pdf, first, second = _two_anchor_groups(tmp_path)
    second = replace(second, parent_id=first.node_id)
    page = replace(
        page, groups=tuple(second if g.node_id == second.node_id else g for g in page.groups)
    )
    result = derive_paired_text_anchor_layout(
        page, pdf, pdf_page=1, canvas=(1200, 800), source_to_page_transform=(1, 0, 0, 1, 600, 0)
    )
    decision = next(d for d in result.decisions if d.group_id == second.node_id)
    assert not decision.accepted
    assert decision.reason == "unsupported-unresolved-ancestor"
    assert decision.fit is None
    assert result.layout is None
