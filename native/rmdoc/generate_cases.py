"""Generate synthetic Rust-reader parity cases from the Python parser regression suite.

Run from the repository root. All binary fixtures and expected outputs stay ignored.
"""

import hashlib
import importlib.util
import json
from dataclasses import asdict
from functools import partial
from pathlib import Path

import pytest

import rm_redraw.parsing.adapter as adapter
from rm_redraw.pipeline import to_render_page

out = Path("artifacts/rmdoc-parity")
out.mkdir(parents=True, exist_ok=True)
original = adapter._parse_stream
cases = {}
spec = importlib.util.spec_from_file_location("browser_reference", Path("native/hosted/bridge.py"))
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def record(stream, page_id, replay_strategy, layout):
    pos = stream.tell()
    raw = stream.read()
    stream.seek(pos)
    result = original(stream, page_id, replay_strategy, layout)
    if replay_strategy != "crdt-order":
        return result
    layout_json = (
        None
        if layout is None
        else {
            "offsets": {str(k): v for k, v in layout.offsets.items()},
            "evidence": layout.evidence,
        }
    )
    identity = hashlib.sha256(
        raw + json.dumps([page_id, layout_json], sort_keys=True).encode()
    ).hexdigest()
    parsed = adapter._json_value(result)
    item = {
        "name": identity,
        "args": {"op": "parse", "page": page_id, "layout": layout_json},
        "parsed": parsed,
    }
    try:
        item["projected"] = asdict(
            to_render_page(
                result, paper_size=(1404, 1872), source_to_page_transform=(1, 0, 0, 1, 702, 0)
            )
        )
    except Exception as e:
        item["project_error"] = str(e)
    (out / (identity + ".rm")).write_bytes(raw)
    cases[identity] = item
    return result


adapter._parse_stream = record
try:
    status = pytest.main(["tests/parsing", "-q", "--basetemp", str(out / "pytest")])
finally:
    adapter._parse_stream = original
if status:
    raise SystemExit(status)
settings = dict(
    width=1404,
    height=1872,
    offset_x=702,
    offset_y=0,
    seconds=2,
    fps=6,
    output_width=468,
    backend="rust",
    allow_clipping=True,
)
for name, item in cases.items():
    raw = (out / (name + ".rm")).read_bytes()
    page = item["args"]["page"]
    item["info"] = bridge.info(raw, page)
    for op, func in [
        ("prepare", partial(bridge.prepare, raw, page, settings, native_timing=True)),
        ("anchors", partial(bridge.anchor_templates, raw, page, settings)),
    ]:
        try:
            item[op] = func()
        except Exception as e:
            item[op + "_error"] = str(e)
    item["settings"] = settings
(out / "cases.json").write_text(
    json.dumps(list(cases.values()), ensure_ascii=False), encoding="utf8"
)
print(f"Saved {len(cases)} synthetic parser cases to {out}")
