"""Generate synthetic v6 block goldens using pinned rmscene; no device files.

Run from the repository root, then set RMDOC_V6_DIFFERENTIAL to the printed
absolute path and run cargo test --test v6 -- --include-ignored.
"""

import json
import runpy
from io import BytesIO
from pathlib import Path

from rmscene import (
    CrdtId,
    CrdtSequenceItem,
    SceneGlyphItemBlock,
    SceneTombstoneItemBlock,
    UnreadableBlock,
    read_blocks,
    simple_text_document,
    write_blocks,
)
from rmscene import scene_items as si

from rm_redraw.parsing.adapter import _json_value


def main():
    cases = []

    def add(name, raw):
        blocks = list(read_blocks(BytesIO(raw)))
        cases.append(
            dict(
                name=name,
                raw=list(raw),
                expected=[
                    dict(
                        fields=_json_value(block),
                        unreadable=isinstance(block, UnreadableBlock),
                        raw_hex=block.data.hex() if isinstance(block, UnreadableBlock) else None,
                        extra_data_hex=block.extra_data.hex() or None,
                        extra_value_data_hex=getattr(block, "extra_value_data", b"").hex() or None,
                    )
                    for block in blocks
                ],
            )
        )

    adapter = runpy.run_path("tests/parsing/test_adapter.py")
    anchors = runpy.run_path("tests/parsing/test_text_anchor_layout.py")
    for name, raw in [
        ("simple", adapter["_synthetic_page"]().getvalue()),
        ("order", adapter["_out_of_order_page"]().getvalue()),
        ("anchors", anchors["_anchored_page"]().getvalue()),
    ]:
        add(name, raw)
        for version in ["3.0", "3.27.3"]:
            output = BytesIO()
            write_blocks(output, read_blocks(BytesIO(raw)), options={"version": version})
            add(name + version, output.getvalue())

    blocks = list(simple_text_document("hello é\nhello世界\n"))
    blocks.extend(
        [
            SceneGlyphItemBlock(
                CrdtId(0, 11),
                CrdtSequenceItem(
                    CrdtId(2, 3),
                    CrdtId(0, 0),
                    CrdtId(0, 0),
                    0,
                    si.GlyphRange(
                        None,
                        5,
                        "world",
                        si.PenColor.YELLOW,
                        [si.Rectangle(2, 3, 4, 5)],
                        (1, 2, 3, 4),
                    ),
                ),
            ),
            SceneTombstoneItemBlock(
                CrdtId(0, 11),
                CrdtSequenceItem(CrdtId(3, 4), CrdtId(0, 0), CrdtId(0, 0), 7, None),
            ),
        ]
    )
    output = BytesIO()
    write_blocks(output, blocks)
    add("text-glyph-tombstone", output.getvalue())
    folder = Path("artifacts/rmdoc-v6")
    folder.mkdir(exist_ok=True)
    path = folder / "cases.json"
    path.write_text(json.dumps(cases), encoding="utf8")
    print(f"{len(cases)} synthetic cases: {path.resolve()}")


if __name__ == "__main__":
    main()
