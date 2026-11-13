"""Package a synthetic reMarkable page and the unmodified Python engine."""

from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from rmscene import (
    CrdtId,
    CrdtSequenceItem,
    LwwValue,
    SceneGroupItemBlock,
    SceneInfo,
    SceneLineItemBlock,
    SceneTreeBlock,
    TreeNodeBlock,
    scene_items,
    write_blocks,
)

ROOT = CrdtId(0, 1)
END = CrdtId(0, 0)


def scene():
    lower, upper = CrdtId(1, 1), CrdtId(1, 2)
    lower_item, upper_item = CrdtId(1, 3), CrdtId(1, 4)
    yield SceneInfo(
        current_layer=LwwValue(CrdtId(1, 5), upper),
        background_visible=LwwValue(CrdtId(1, 6), True),
        root_document_visible=LwwValue(CrdtId(1, 7), False),
        paper_size=(128, 96),
    )
    for layer in (lower, upper):
        yield SceneTreeBlock(layer, layer, False, ROOT)
        yield TreeNodeBlock(scene_items.Group(node_id=layer))
    yield SceneGroupItemBlock(ROOT, CrdtSequenceItem(lower_item, END, upper_item, 0, lower))
    yield SceneGroupItemBlock(ROOT, CrdtSequenceItem(upper_item, lower_item, END, 0, upper))
    pen = scene_items.Pen
    specs = (
        (lower, pen.FINELINER_2, (26, 45, 86, 255), (9, 30, 100, 55), 25),
        (upper, pen.PENCIL_2, (41, 57, 79, 234), (14, 15, 115, 68), 78),
        (lower, pen.HIGHLIGHTER_2, (250, 217, 67, 180), (12, 62, 114, 35), 66),
        (upper, pen.PAINTBRUSH_2, (191, 55, 67, 207), (19, 65, 111, 22), 78),
        (lower, pen.ERASER, (0, 0, 0, 255), (65, 18, 62, 72), 46),
        (upper, pen.CALIGRAPHY, (24, 83, 47, 227), (31, 71, 113, 75), 38),
    )
    last_ids = {lower: END, upper: END}
    for index, (layer, tool, rgba, (x1, y1, x2, y2), width) in enumerate(specs, 10):
        item_id = CrdtId(1, index)
        points = [
            scene_items.Point(x1, y1, 14, 20, width, 110),
            scene_items.Point((x1 + x2) / 2, (y1 + y2) / 2 + 4, 23, 49, width, 200),
            scene_items.Point(x2, y2, 30, 78, width, 155),
        ]
        line = scene_items.Line(scene_items.PenColor.BLACK, tool, points, 1.5, 0, color_rgba=rgba)
        yield SceneLineItemBlock(layer, CrdtSequenceItem(item_id, last_ids[layer], END, 0, line))
        last_ids[layer] = item_id


def main():
    root = Path(__file__).resolve().parents[2]
    output = root / "artifacts/browser-prototype-20261113"
    output.mkdir(parents=True, exist_ok=True)
    page = BytesIO()
    write_blocks(page, list(scene()), options={"version": "3.27.3"})
    with ZipFile(output / "synthetic.rmdoc", "w", ZIP_DEFLATED) as archive:
        archive.writestr("page.rm", page.getvalue())
    source = root / "src"
    package = source / "rm_redraw"
    modules = [
        package / "__init__.py",
        package / "pipeline.py",
        package / "replay/__init__.py",
        package / "replay/schedule.py",
        *sorted((package / "parsing").glob("*.py")),
        *sorted((package / "rendering").glob("*.py")),
    ]
    with ZipFile(output / "engine.zip", "w", ZIP_DEFLATED) as archive:
        for module in modules:
            archive.write(module, module.relative_to(source).as_posix())
        archive.write(Path(__file__).with_name("render_probe.py"), "render_probe.py")


if __name__ == "__main__":
    main()
