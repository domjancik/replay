"""Generate public synthetic differential cases against the Python anchor fitter."""

import json
import runpy
from dataclasses import asdict, replace
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from rm_redraw.comparison.anchor_fit import fit_anchor_template
from rm_redraw.parsing import parse_page
from rm_redraw.pipeline import to_render_page
from rm_redraw.replay.schedule import duration_schedule

out = Path("artifacts/rust-anchor-validation")
out.mkdir(exist_ok=True)
cases = []
for scenario in ["unique", "repeated", "filled", "wrong", "diagonal", "fractional", "multi"]:
    image = Image.new("1", (180, 180), 0)
    draw = ImageDraw.Draw(image)
    strokes = [[(0, 0), (0, 24), (20, 24)]]
    if scenario == "filled":
        draw.rectangle((66, 72, 102, 126), fill=1)
    elif scenario == "wrong":
        draw.line([(70, 90), (70, 130)], fill=1, width=3)
    else:
        if scenario == "diagonal":
            strokes = [[(0, 0), (12, 24), (30, 6)]]
        if scenario == "fractional":
            strokes = [[(0.25, 0.25), (0.75, 24.25), (20.25, 24.25)]]
        if scenario == "multi":
            strokes.append([(25, 5), (37, 12), (24, 24)])
        for ty in [40, 110] if scenario == "repeated" else [90]:
            for stroke in strokes:
                draw.line([(x + 70, y + ty) for x, y in stroke], fill=1, width=3)
    mask = np.asarray(image, dtype=np.uint8)
    expected = asdict(fit_anchor_template(mask, [np.asarray(s) for s in strokes], expected_x=70))
    cases.append(
        dict(
            name=scenario,
            request=dict(
                width=180,
                height=180,
                mask=mask.ravel().tolist(),
                templates=[dict(strokes=strokes, expected_x=70)],
            ),
            expected=expected,
        )
    )
(out / "cases.json").write_text(json.dumps(cases), encoding="utf8")
print(len(cases), "reference cases")


raw = runpy.run_path("tests/parsing/test_legacy_v5.py")["legacy_page"]()
page = to_render_page(parse_page(BytesIO(raw), page_id="timing"), paper_size=(100, 100))
page = replace(
    page,
    strokes=tuple(
        replace(page.strokes[0], stroke_id=str(i), group_id="0:2" if i % 2 else "0:3")
        for i in range(7)
    ),
    replay_order=tuple(str(i) for i in reversed(range(7))),
)
schedules = []
for ordering in ["entry", "layer"]:
    for seconds, fps in [(2, 6), (2.3, 12), (6, 30)]:
        expected = []
        for f in duration_schedule(
            page, fps=fps, duration_seconds=seconds, final_hold_seconds=1, ordering=ordering
        ):
            v = asdict(f.visibility)
            v["completed_stroke_ids"] = sorted(v["completed_stroke_ids"])
            expected.append(v)
        schedules.append(
            dict(
                request=dict(
                    op="schedule", page=asdict(page), seconds=seconds, fps=fps, ordering=ordering
                ),
                expected=expected,
            )
        )
(out / "schedules.json").write_text(json.dumps(schedules), encoding="utf8")