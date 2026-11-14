"""Opt-in offline parity capture; never contacts a tablet or modifies raw inputs."""

import argparse
import hashlib
import importlib.util
import json
from functools import partial
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from rm_redraw.parsing import parse_page
from rm_redraw.parsing.adapter import _json_value

p = argparse.ArgumentParser()
p.add_argument("--archive", action="append", required=True, type=Path)
p.add_argument("--out", required=True, type=Path)
p.add_argument("--pages", default="1,12")
args = p.parse_args()
args.out.mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location("reference_bridge", Path("native/hosted/bridge.py"))
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
cases = []
archives = []
for path in args.archive:
    data = path.read_bytes()
    record = bridge.inspect(data)
    digest = hashlib.sha256(data).hexdigest()
    (args.out / (digest + ".rmdoc")).write_bytes(data)
    archives.append({"name": digest, "expected": record})
    with ZipFile(BytesIO(data)) as archive:
        for entry in record["pages"]:
            if (
                entry["number"] not in {int(x) for x in args.pages.split(",")}
                or not entry["available"]
            ):
                continue
            raw = archive.read(entry["member"])
            name = hashlib.sha256(raw).hexdigest()
            (args.out / (name + ".rm")).write_bytes(raw)
            page = parse_page(BytesIO(raw), page_id=entry["id"])
            w, h = page.paper_size or (1404, 1872)
            w = min(max(w, 64), 4096)
            h = min(max(h, 64), 8192)
            if w * h > 12000000:
                h = 12000000 // w
            settings = dict(
                width=w,
                height=h,
                offset_x=w / 2,
                offset_y=0,
                seconds=2,
                fps=6,
                output_width=468,
                backend="rust",
                allow_clipping=True,
            )
            item = {
                "name": name,
                "args": {"op": "parse", "page": entry["id"], "layout": None},
                "parsed": _json_value(page),
                "info": bridge.info(raw, entry["id"]),
                "settings": settings,
            }
            for op, func in [
                (
                    "prepare",
                    partial(bridge.prepare, raw, entry["id"], settings, native_timing=True),
                ),
                ("anchors", partial(bridge.anchor_templates, raw, entry["id"], settings)),
            ]:
                try:
                    item[op] = func()
                except Exception as e:
                    item[op + "_error"] = str(e)
            cases.append(item)
(args.out / "cases.json").write_text(json.dumps(cases, ensure_ascii=False), encoding="utf8")
(args.out / "archives.json").write_text(json.dumps(archives, ensure_ascii=False), encoding="utf8")
print(
    f"Captured {len(cases)} page cases and {len(archives)} archives; private outputs at {args.out}"
)
