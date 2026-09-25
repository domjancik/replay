from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from io import BytesIO

import pytest
from PIL import Image, ImageChops
from pypdf import PdfWriter
from pypdf.generic import StreamObject
from rmscene import (
    CrdtId,
    CrdtSequenceItem,
    LwwValue,
    RootTextBlock,
    SceneGroupItemBlock,
    SceneLineItemBlock,
    SceneTreeBlock,
    TreeNodeBlock,
    simple_text_document,
    write_blocks,
)
from rmscene import scene_items as si

from rm_redraw.replay.__main__ import main
from rm_redraw.replay.command import ReplayCommandError, run_local_replay


def _source(path):
    end, layer, group = CrdtId(0, 0), CrdtId(0, 11), CrdtId(40, 100)
    blocks = [
        replace(block, value=replace(block.value, pos_y=234.0))
        if isinstance(block, RootTextBlock)
        else block
        for block in simple_text_document("\n\n")
    ]
    blocks.extend(
        [
            SceneTreeBlock(group, end, True, layer),
            TreeNodeBlock(
                si.Group(
                    group,
                    anchor_id=LwwValue(CrdtId(40, 110), CrdtId(1, 17)),
                    anchor_type=LwwValue(CrdtId(40, 111), 2),
                    anchor_threshold=LwwValue(CrdtId(40, 112), 35.0),
                    anchor_origin_x=LwwValue(CrdtId(40, 113), 70.0),
                )
            ),
            SceneGroupItemBlock(layer, CrdtSequenceItem(CrdtId(40, 114), end, end, 0, group)),
            SceneLineItemBlock(
                group,
                CrdtSequenceItem(
                    CrdtId(40, 115),
                    end,
                    end,
                    0,
                    si.Line(
                        color=si.PenColor.BLACK,
                        tool=si.Pen.BALLPOINT_2,
                        points=[
                            si.Point(x, y, 2, 0, 12, 0) for x, y in ((0, 0), (0, 24), (20, 24))
                        ],
                        thickness_scale=2.0,
                        starting_length=0.0,
                    ),
                ),
            ),
        ]
    )
    data = BytesIO()
    write_blocks(data, blocks, options={"version": "3.27.3"})
    path.write_bytes(data.getvalue())
    return path


def _native(path, *, ambiguous=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=180, height=180)
    content = StreamObject()
    shapes = b"70 90 m 70 114 l 90 114 l S "
    if ambiguous:
        shapes += b"70 40 m 70 64 l 90 64 l S "
    content.set_data(b"1 0 0 -1 0 180 cm 0 G 3 w " + shapes)
    page.replace_contents(content)
    writer.write(path)
    return path


@pytest.mark.parametrize("boundary", [False, True])
def test_auto_anchors_apply_native_match_and_record_provenance(tmp_path, boundary):
    source = _source(tmp_path / "source.rm")
    original = source.read_bytes()
    native = _native(tmp_path / "native.pdf")
    output = tmp_path / "output"
    assert (
        main(
            [
                str(source),
                "--output",
                str(output),
                *(["--pencil-boundary"] if boundary else []),
                "--auto-text-anchors",
                "--paired-native-pdf",
                str(native),
                "--export-canvas",
                "180",
                "180",
                "--source-affine",
                "1",
                "0",
                "0",
                "1",
                "0",
                "0",
            ]
        )
        == 0
    )
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["backend"]["texture_profile"] == (
        "experimental-texture-v5-sparse-boundary"
        if boundary
        else "experimental-texture-v6-app-png"
    )
    assert manifest["backend"]["brush_profile"] == "experimental-brush-app-png-v1"
    assert manifest["backend"]["calligraphy_profile"] == "provisional-calligraphy-raw-width-v1"
    assert manifest["backend"]["calligraphy_antialiasing"] == "4x-pixel-center-area-coverage"
    assert manifest["backend"]["texture_native_calibrated"] is False
    layout = manifest["text_anchor_layout"]
    assert layout["origin"] == "automatic-paired-native-pdf"
    assert layout["offsets"]["1:17"] == pytest.approx(-144.0, abs=2)
    assert layout["decisions"][0]["accepted"] is True
    assert layout["decisions"][0]["group_id"] == "40:100"
    assert layout["decisions"][0]["reason"]
    assert (
        layout["provenance"]["native_pdf_sha256"] == hashlib.sha256(native.read_bytes()).hexdigest()
    )
    assert manifest["final_frame_matches_static"] is True
    image = Image.open(output / "static.png").convert("RGB")
    bounds = ImageChops.difference(image, Image.new("RGB", image.size, "white")).getbbox()
    assert bounds is not None and 85 <= bounds[1] <= 92
    assert source.read_bytes() == original


@pytest.mark.parametrize("manual", [False, True])
def test_auto_anchors_validate_required_and_conflicting_options(tmp_path, manual):
    source = _source(tmp_path / "source.rm")
    with pytest.raises(
        ReplayCommandError, match="--text-anchor-layout" if manual else "--paired-native-pdf"
    ):
        run_local_replay(
            source,
            output_directory=tmp_path / "output",
            auto_text_anchors=True,
            text_anchor_layout=tmp_path / "unused.json" if manual else None,
        )
    assert not (tmp_path / "output").exists()


def test_auto_anchors_reject_ambiguous_match_before_output(tmp_path):
    source = _source(tmp_path / "source.rm")
    with pytest.raises(ReplayCommandError, match="40:100.*1:17.*ambiguous"):
        run_local_replay(
            source,
            output_directory=tmp_path / "output",
            auto_text_anchors=True,
            paired_native_pdf=_native(tmp_path / "native.pdf", ambiguous=True),
            export_canvas=(180, 180),
            source_affine=(1, 0, 0, 1, 0, 0),
        )
    assert not (tmp_path / "output").exists()


def test_auto_anchors_noop_without_applicable_groups(tmp_path):
    source = tmp_path / "text-only.rm"
    data = BytesIO()
    write_blocks(data, simple_text_document("hello"), options={"version": "3.27.3"})
    source.write_bytes(data.getvalue())
    result = run_local_replay(
        source,
        output_directory=tmp_path / "output",
        auto_text_anchors=True,
        paired_native_pdf=_native(tmp_path / "native.pdf"),
        export_canvas=(180, 180),
    )
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["text_anchor_layout"]["origin"] == "automatic-paired-native-pdf"
    assert manifest["text_anchor_layout"]["offsets"] == {}
    assert manifest["text_anchor_layout"]["decisions"] == []
    assert manifest["text_anchor_layout"]["evidence"] is None


def test_auto_anchors_reports_unsupported_transform_without_output(tmp_path, capsys):
    source = _source(tmp_path / "source.rm")
    native = _native(tmp_path / "native.pdf")
    output = tmp_path / "output"
    assert (
        main(
            [
                str(source),
                "--output",
                str(output),
                "--auto-text-anchors",
                "--paired-native-pdf",
                str(native),
                "--export-canvas",
                "180",
                "180",
                "--source-affine",
                "2",
                "0",
                "0",
                "1",
                "0",
                "0",
            ]
        )
        == 2
    )
    assert "translation-only" in capsys.readouterr().err
    assert not output.exists()
