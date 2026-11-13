"""One-at-a-time local replay jobs, using the existing CLI unchanged."""

import json
import logging
import math
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

from rm_redraw.parsing import parse_page
from rm_redraw.pipeline import to_render_page
from rm_redraw.replay.schedule import ordered_stroke_ids

from .anchor_layouts import anchor_arguments
from .library import Library, _local_id

LOGGER = logging.getLogger(__name__)


class CanvasClippingError(ValueError):
    """A visible stroke center falls outside the selected replay canvas."""


def validate_settings(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Settings must be a JSON object")

    def number(key, low, high, *, integer=False):
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} must be a number")
        if not low <= value <= high:
            raise ValueError(f"{key} must be between {low} and {high}")
        if integer and int(value) != value:
            raise ValueError(f"{key} must be an integer")
        return int(value) if integer else value

    width = number("width", 64, 4096, integer=True)
    height = number("height", 64, 8192, integer=True)
    if width * height > 12_000_000:
        raise ValueError("Canvas exceeds the local utility's 12 megapixel limit")
    output = number("output_width", 128, 1404, integer=True)
    output += output % 2
    out_height = max(2, round(output * height / width / 2) * 2)
    if out_height > 4096:
        raise ValueError("Output is too tall; reduce output width")
    seconds = number("seconds", 2, 60)
    fps = number("fps", 6, 30, integer=True)
    ordering = data.get("ordering", "layer")
    if ordering not in ("layer", "entry"):
        raise ValueError("Unknown replay ordering")
    backend = data.get("backend")
    if backend not in ("python", "rust"):
        raise ValueError("Unknown pencil backend")
    allow_clipping = data.get("allow_clipping", False)
    if type(allow_clipping) is not bool:
        raise ValueError("allow_clipping must be true or false")
    return {
        "paper_size": (width, height),
        "source_affine": (
            1,
            0,
            0,
            1,
            number("offset_x", -8192, 8192),
            number("offset_y", -8192, 8192),
        ),
        "viewport": (output, out_height),
        "seconds": seconds,
        "fps": fps,
        "backend": backend,
        "ordering": ordering,
        "allow_clipping": allow_clipping,
    }


def page_info(library: Library, document_id: str, page_id: str) -> tuple[dict, object]:
    document = library.get(document_id)
    entry = next((p for p in document["pages"] if p["id"] == page_id), None)
    if entry is None or not entry["available"]:
        raise ValueError("This page has no saved stroke data")
    with ZipFile(library.source(document_id)) as archive:
        parsed = parse_page(BytesIO(archive.read(entry["member"])), page_id=page_id)
    return {
        "number": entry["number"],
        "strokes": len(parsed.strokes),
        "paper_size": parsed.paper_size,
        "source_to_page_transform": parsed.source_to_page_transform,
        "unresolved_anchors": sum(not s.effective_transform.resolved for s in parsed.strokes),
        "warnings": list(parsed.diagnostics.warnings),
    }, parsed


class Jobs:
    def __init__(self, root: Path, library: Library):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.library = library
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="replay")
        self.jobs = {}
        self.processes = {}
        for path in self.root.glob("*/job.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
                if (
                    not isinstance(job, dict)
                    or not _local_id(path.parent.name)
                    or job.get("id") != path.parent.name
                    or type(job.get("created")) not in (int, float)
                    or job.get("state")
                    not in ("queued", "running", "complete", "failed", "cancelled", "interrupted")
                ):
                    raise ValueError("Malformed job record")
            except (OSError, ValueError, RecursionError):
                LOGGER.warning("Ignoring unreadable replay job record %s", path.parent.name)
                continue
            if job["state"] in ("queued", "running"):
                job.update(
                    state="interrupted",
                    error="Server stopped before this job finished",
                    finished=time.time(),
                )
                self._save_status(job)
            self.jobs[job["id"]] = job

    def _save(self, job):
        folder = self.root / job["id"]
        folder.mkdir(exist_ok=True)
        path = folder / "job.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(job, indent=2), encoding="utf-8")
        temporary.replace(path)

    def _save_status(self, job):
        try:
            self._save(job)
        except OSError:
            LOGGER.warning("Could not persist replay status for job %s", job["id"])

    def submit(self, document_id: str, page_id: str, settings: dict) -> dict:
        config = validate_settings(settings)
        document = self.library.get(document_id)
        info, parsed = page_info(self.library, document_id, page_id)
        if info["unresolved_anchors"] and not document["has_pdf"]:
            raise ValueError(
                "This page needs text-anchor placement. Import it from USB with "
                "the matching PDF enabled, then retry."
            )
        if config["backend"] == "rust":
            from rm_redraw.rendering.native_pencil import native_info

            native_info()
        page = to_render_page(
            parsed,
            paper_size=config["paper_size"],
            source_to_page_transform=config["source_affine"],
        )
        visible = set(ordered_stroke_ids(page, config["ordering"]))
        if not visible:
            raise ValueError("Page has no visible strokes to replay")
        if not config["allow_clipping"]:
            unresolved = {
                str(stroke.stroke_id)
                for stroke in parsed.strokes
                if not stroke.effective_transform.resolved
            }
            width, height = config["paper_size"]
            if any(
                not (0 <= point.x <= width and 0 <= point.y <= height)
                for stroke in page.strokes
                if stroke.stroke_id in visible and stroke.stroke_id not in unresolved
                for point in stroke.points
            ):
                raise CanvasClippingError(
                    "Visible stroke points fall outside the selected canvas. "
                    "Adjust the canvas dimensions or offsets, or allow clipping."
                )
        with self.lock:
            if sum(j["state"] in ("queued", "running") for j in self.jobs.values()) >= 8:
                raise ValueError("Queue is full (8 jobs); wait for a job to finish")
            job = {
                "id": uuid4().hex,
                "name": document["name"],
                "page": info["number"],
                "document_id": document_id,
                "page_id": page_id,
                "settings": config,
                "state": "queued",
                "created": time.time(),
                "strokes": len(visible),
                "expected_frames": math.ceil(config["seconds"] * config["fps"]) + config["fps"],
            }
            self._save(job)
            self.jobs[job["id"]] = job
            self.executor.submit(self._run, job["id"])
            return dict(job)

    def submit_export(self, source_job_id, crop, reverse_speed):
        from PIL import Image

        from .export import crop_bounds, replay_indices

        with self.lock:
            source = self.jobs.get(source_job_id)
            if not source or source["state"] != "complete" or source.get("kind") == "export":
                raise ValueError("Select a completed original replay")
            if sum(j["state"] in ("queued", "running") for j in self.jobs.values()) >= 8:
                raise ValueError("Queue is full (8 jobs)")
            folder = self.root / source_job_id / "output"
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            with Image.open(folder / "static.png") as image:
                bounds = crop_bounds(crop, image.size)
            fps = manifest["replay"]["fps"]
            indices = replay_indices(
                manifest["frame_count"],
                math.ceil(manifest["replay"]["final_hold_seconds"] * fps),
                reverse_speed,
            )
            config = dict(source["settings"])
            config["viewport"] = [bounds[2] - bounds[0], bounds[3] - bounds[1]]
            job = {
                "id": uuid4().hex,
                "kind": "export",
                "source_job": source_job_id,
                "crop": crop,
                "reverse_speed": reverse_speed,
                "name": source["name"] + (" · loop" if reverse_speed else " · crop"),
                "page": source["page"],
                "document_id": source["document_id"],
                "page_id": source["page_id"],
                "settings": config,
                "state": "queued",
                "created": time.time(),
                "expected_frames": len(indices),
            }
            self._save(job)
            self.jobs[job["id"]] = job
            self.executor.submit(self._run, job["id"])
            return dict(job)

    def _run(self, job_id):
        job = self.jobs[job_id]
        try:
            with self.lock:
                if job["state"] != "queued":
                    return
                job.update(state="running", started=time.time())
                self._save(job)
            if job.get("kind") == "export":
                output = self.root / job_id / "output"
                args = [
                    sys.executable,
                    "-m",
                    "rm_redraw.web.export",
                    str(self.root / job["source_job"] / "output"),
                    str(output),
                    "--reverse-speed",
                    str(job["reverse_speed"]),
                ]
                if job["crop"] is not None:
                    args += ["--crop", *map(str, job["crop"])]
            else:
                document = self.library.get(job["document_id"])
                config = job["settings"]
                output = self.root / job_id / "output"
                args = [
                    sys.executable,
                    "-m",
                    "rm_redraw.replay",
                    str(self.library.source(job["document_id"])),
                    "--output",
                    str(output),
                    "--page-id",
                    job["page_id"],
                    "--paper-size",
                    *map(str, config["paper_size"]),
                    "--source-affine",
                    *map(str, config["source_affine"]),
                    "--viewport",
                    *map(str, config["viewport"]),
                    "--fps",
                    str(config["fps"]),
                    "--ordering",
                    config.get("ordering", "layer"),
                    "--mode",
                    "duration",
                    "--duration",
                    str(config["seconds"]),
                    "--final-hold",
                    "1",
                    "--pencil-backend",
                    config["backend"],
                ]
                if document["has_pdf"]:
                    args += anchor_arguments(
                        self.library.source(job["document_id"]),
                        job["page_id"],
                        job["page"],
                        config,
                    )
                    args += [
                        "--paired-native-pdf",
                        str(self.library.source(job["document_id"]).with_name("native.pdf")),
                        "--paired-pdf-page",
                        str(job["page"]),
                        "--export-canvas",
                        *map(str, config["paper_size"]),
                    ]
            with (self.root / job_id / "render.log").open("wb") as log:
                with self.lock:
                    if job["state"] == "cancelled":
                        return
                    process = subprocess.Popen(
                        args,
                        stdout=log,
                        stderr=log,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    )
                    self.processes[job_id] = process
                code = process.wait()
            with self.lock:
                self.processes.pop(job_id, None)
                if job["state"] == "cancelled":
                    return
                if code:
                    detail = (self.root / job_id / "render.log").read_text(
                        encoding="utf-8", errors="replace"
                    )[-2500:]
                    raise ValueError(detail or f"Renderer exited with status {code}")
                manifest = json.loads((output / "manifest.json").read_text())
                if (
                    not manifest.get(
                        "forward_final_frame_matches_static", manifest["final_frame_matches_static"]
                    )
                    or not (output / "replay.mp4").exists()
                ):
                    raise ValueError("Replay did not pass final-frame verification")
                job.update(
                    state="complete", finished=time.time(), expected_frames=manifest["frame_count"]
                )
                self._save(job)
        except Exception as error:
            with self.lock:
                if job["state"] != "cancelled":
                    job.update(state="failed", error=str(error), finished=time.time())
                    self._save_status(job)

    def cancel(self, job_id):
        with self.lock:
            job = self.jobs[job_id]
            if job["state"] not in ("queued", "running"):
                return
            job.update(state="cancelled", finished=time.time())
            self._save_status(job)
            process = self.processes.get(job_id)
            if process is not None and process.poll() is None:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        check=False,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                else:
                    process.terminate()

    def list(self):
        with self.lock:
            result = []
            for job in sorted(self.jobs.values(), key=lambda j: j["created"], reverse=True):
                count = len(list((self.root / job["id"] / "output/frames").glob("frame_*.png")))
                result.append(
                    {
                        **job,
                        "frames": job.get("expected_frames", count)
                        if job["state"] == "complete"
                        else count,
                    }
                )
            return result

    def media(self, job_id, filename) -> Path:
        with self.lock:
            if job_id not in self.jobs:
                raise ValueError("Unknown job")
            folder = self.root / job_id / "output"
            if filename == "latest.png":
                frames = sorted((folder / "frames").glob("frame_*.png"))
                if len(frames) < 2:
                    raise ValueError("No preview yet")
                return frames[-2]  # The latest file may still be being written.
            if filename not in ("static.png", "replay.mp4", "manifest.json"):
                raise ValueError("Unknown output")
            if self.jobs[job_id]["state"] != "complete":
                raise ValueError("Output is not complete")
            return folder / filename

    def close(self):
        for job in self.list():
            self.cancel(job["id"])
        self.executor.shutdown(wait=True, cancel_futures=True)
