from __future__ import annotations

import json
from dataclasses import replace
from io import BytesIO

import pytest
from PIL import Image, ImageChops
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

END = CrdtId(0, 0)
TEXT_LAYER = CrdtId(0, 11)


def _anchored_page_bytes() -> bytes:
    group_id = CrdtId(40, 100)
    blocks = []
    for block in simple_text_document("\n\n"):
        if isinstance(block, RootTextBlock):
            block = replace(block, value=replace(block.value, pos_y=234.0))
        blocks.append(block)
    blocks.extend(
        [
            SceneTreeBlock(group_id, END, True, TEXT_LAYER),
            TreeNodeBlock(
                si.Group(
                    group_id,
                    anchor_id=LwwValue(CrdtId(40, 110), CrdtId(1, 17)),
                    anchor_type=LwwValue(CrdtId(40, 111), 2),
                    anchor_threshold=LwwValue(CrdtId(40, 112), 35.74803161621094),
                    anchor_origin_x=LwwValue(CrdtId(40, 113), 10.0),
                )
            ),
            SceneGroupItemBlock(
                TEXT_LAYER,
                CrdtSequenceItem(CrdtId(40, 114), END, END, 0, group_id),
            ),
            SceneLineItemBlock(
                group_id,
                CrdtSequenceItem(
                    CrdtId(40, 115),
                    END,
                    END,
                    0,
                    si.Line(
                        color=si.PenColor.BLACK,
                        tool=si.Pen.BALLPOINT_2,
                        points=[
                            si.Point(50.0, -10.0, 2, 0, 12, 0),
                            si.Point(70.0, -10.0, 2, 0, 12, 0),
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
    return data.getvalue()


def test_cli_applies_and_records_text_anchor_layout(tmp_path) -> None:
    source = tmp_path / "anchored.rm"
    source.write_bytes(_anchored_page_bytes())
    layout_path = tmp_path / "anchor-layout.json"
    layout_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "evidence": "controlled native registration",
                "offsets": {"1:17": -220.0},
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "output"

    exit_code = main(
        [
            str(source),
            "--output",
            str(output),
            "--paper-size",
            "128",
            "128",
            "--source-affine",
            "1",
            "0",
            "0",
            "1",
            "0",
            "0",
            "--viewport",
            "128",
            "128",
            "--text-anchor-layout",
            str(layout_path),
        ]
    )

    assert exit_code == 0
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["text_anchor_layout"] == {
        "evidence": "controlled native registration",
        "offsets": {"1:17": -220.0},
        "path": str(layout_path),
        "schema_version": 1,
    }
    image = Image.open(output / "static.png").convert("RGB")
    ink_bounds = ImageChops.difference(image, Image.new("RGB", image.size, "white")).getbbox()
    assert ink_bounds is not None
    assert ink_bounds[1] < 12


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {
                "schema_version": 1,
                "evidence": "overflow",
                "offsets": {"1:17": 10**400},
            },
            "finite",
        ),
        (
            {
                "schema_version": True,
                "evidence": "wrong schema type",
                "offsets": {"1:17": 20.0},
            },
            "schema_version",
        ),
        (
            {
                "schema_version": 1,
                "evidence": "noncanonical ID",
                "offsets": {"01:17": 20.0},
            },
            "anchor ID",
        ),
    ],
)
def test_cli_rejects_invalid_text_anchor_layout(
    tmp_path, capsys, payload: dict[str, object], message: str
) -> None:
    source = tmp_path / "anchored.rm"
    source.write_bytes(_anchored_page_bytes())
    layout_path = tmp_path / "anchor-layout.json"
    layout_path.write_text(json.dumps(payload), encoding="utf-8")

    exit_code = main(
        [
            str(source),
            "--output",
            str(tmp_path / "output"),
            "--paper-size",
            "128",
            "128",
            "--source-affine",
            "1",
            "0",
            "0",
            "1",
            "0",
            "0",
            "--text-anchor-layout",
            str(layout_path),
        ]
    )

    assert exit_code == 2
    assert message in capsys.readouterr().err
