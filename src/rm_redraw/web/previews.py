"""Bounded static selection previews, serialized with replay rendering."""

import hashlib
import json
import re
import threading
from uuid import uuid4

from rm_redraw.replay.command import run_local_replay

from .anchor_layouts import anchor_arguments
from .jobs import validate_settings


class Previews:
    def __init__(self, root, library, executor):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.library, self.executor = library, executor
        self.records = {}
        self.lock = threading.RLock()

    def image(self, key):
        if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key):
            raise ValueError("Invalid preview ID")
        return self.root / (key + ".png")

    def get(self, key):
        with self.lock:
            if self.image(key).is_file():
                return {"id": key, "state": "complete", "url": f"/page-previews/{key}.png"}
            if key not in self.records:
                raise ValueError("Unknown preview")
            return dict(self.records[key])

    def submit(self, document_id, page_id, settings):
        config = validate_settings(settings)
        document = self.library.get(document_id)
        entry = next((p for p in document["pages"] if p["id"] == page_id and p["available"]), None)
        if entry is None:
            raise ValueError("This page has no saved stroke data")
        source = self.library.source(document_id)
        layout = {}
        if document["has_pdf"]:
            args = anchor_arguments(source, page_id, entry["number"], config)
            layout = (
                {"text_anchor_layout": args[1]} if len(args) == 2 else {"auto_text_anchors": True}
            )
        binding = dict(
            version=1,
            source=document["sha256"],
            pdf=document.get("pdf_sha256"),
            page=page_id,
            paper=config["paper_size"],
            affine=config["source_affine"],
            backend=config["backend"],
        )
        if "text_anchor_layout" in layout:
            from pathlib import Path

            binding["layout"] = hashlib.sha256(
                Path(layout["text_anchor_layout"]).read_bytes()
            ).hexdigest()
        key = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
        with self.lock:
            if self.image(key).is_file() or key in self.records:
                return self.get(key)
            if sum(r["state"] in ("queued", "running") for r in self.records.values()) >= 4:
                raise ValueError("Preview queue is busy; select this page again shortly")
            self.records[key] = {"id": key, "state": "queued"}
            self.executor.submit(
                self._render,
                key,
                source,
                page_id,
                entry["number"],
                config,
                document["has_pdf"],
                layout,
            )
            return dict(self.records[key])

    def _render(self, key, source, page_id, page_number, config, has_pdf, layout):
        with self.lock:
            self.records[key]["state"] = "running"
        try:
            width, height = config["paper_size"]
            scale = min(280 / width, 400 / height)
            viewport = tuple(max(2, round(v * scale / 2) * 2) for v in (width, height))
            evidence = (
                dict(
                    paired_native_pdf=source.with_name("native.pdf"),
                    paired_pdf_page=page_number,
                    export_canvas=config["paper_size"],
                    **layout,
                )
                if has_pdf
                else {}
            )
            result = run_local_replay(
                source,
                output_directory=self.root / (key + "-" + uuid4().hex),
                page_id=page_id,
                paper_size=config["paper_size"],
                source_affine=config["source_affine"],
                viewport=viewport,
                pencil_backend=config["backend"],
                static_only=True,
                **evidence,
            )
            (result.output_directory / "static.png").replace(self.image(key))
            with self.lock:
                self.records[key]["state"] = "complete"
        except Exception as error:
            with self.lock:
                self.records[key].update(state="failed", error=str(error))
