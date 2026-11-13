"""Exercise an installed package locally with synthetic data; requires FFmpeg on PATH."""

import argparse
import hashlib
import http.client
import json
import sys
import tempfile
import threading
import time
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from rmscene import (
    CrdtId,
    CrdtSequenceItem,
    LwwValue,
    SceneGroupItemBlock,
    SceneLineItemBlock,
    SceneTreeBlock,
    TreeNodeBlock,
    write_blocks,
)
from rmscene import scene_items as si

import rm_redraw
from rm_redraw.web.server import create_server


def synthetic_archive():
    end, root, layer = CrdtId(0, 0), CrdtId(0, 1), CrdtId(4, 10)
    blocks = [
        SceneTreeBlock(layer, layer, False, root),
        TreeNodeBlock(si.Group(layer, visible=LwwValue(CrdtId(4, 1), True))),
        SceneGroupItemBlock(root, CrdtSequenceItem(CrdtId(4, 11), end, end, 0, layer)),
        SceneLineItemBlock(
            layer,
            CrdtSequenceItem(
                CrdtId(4, 12),
                end,
                end,
                0,
                si.Line(
                    si.PenColor.BLACK,
                    si.Pen.BALLPOINT_2,
                    [si.Point(8, 8, 1, 1, 8, 255), si.Point(50, 50, 1, 1, 8, 255)],
                    2.0,
                    0.0,
                ),
            ),
        ),
    ]
    raw = BytesIO()
    write_blocks(raw, blocks, options={"version": "3.27.3"})
    archive = BytesIO()
    with ZipFile(archive, "w") as z:
        z.writestr("doc.content", json.dumps({"pages": ["page"]}))
        z.writestr("doc/page.rm", raw.getvalue())
    return archive.getvalue()


def request(port, path, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path, headers=headers or {})
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


def wait_job(queue, job_id):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        job = next(item for item in queue.list() if item["id"] == job_id)
        if job["state"] not in ("queued", "running"):
            if job["state"] != "complete":
                raise RuntimeError(f"Job failed: {job}")
            return job
        time.sleep(0.05)
    raise TimeoutError("Job did not complete within 60 seconds")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-source", action="store_true", help="allow source checkout for tests"
    )
    args = parser.parse_args()
    package = Path(rm_redraw.__file__).resolve()
    checkout = Path(__file__).resolve().parent.parent
    if not args.allow_source and (
        package.is_relative_to(checkout / "src") or Path.cwd().is_relative_to(checkout)
    ):
        raise RuntimeError(
            "Run outside the checkout with the wheel installed in a clean environment"
        )
    with tempfile.TemporaryDirectory(prefix="rm-redraw-smoke-") as tmp:
        server = create_server(Path(tmp), port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, headers, index = request(server.server_port, "/")
            if status != 200 or not index:
                raise RuntimeError("Index request failed")
            cookie = headers["Set-Cookie"].split(";")[0]
            status, _, body = request(server.server_port, "/api/session", {"Cookie": cookie})
            if status != 200 or not json.loads(body).get("token"):
                raise RuntimeError("Session request failed")
            for asset in ("/app.js", "/style.css"):
                status, _, body = request(server.server_port, asset)
                if status != 200 or not body:
                    raise RuntimeError(f"Asset request failed: {asset}")
            library, queue = server.app.library, server.app.jobs
            document = library.add(synthetic_archive(), provenance={"provider": "synthetic-smoke"})
            settings = {
                "width": 64,
                "height": 64,
                "offset_x": 0,
                "offset_y": 0,
                "seconds": 2,
                "fps": 6,
                "output_width": 128,
                "backend": "python",
                "ordering": "entry",
            }
            job = queue.submit(document["id"], "page", settings)
            wait_job(queue, job["id"])
            folder = queue.root / job["id"] / "output"
            manifest = json.loads((folder / "manifest.json").read_text())
            frames = sorted((folder / "frames").glob("*.png"))
            if (
                not manifest["final_frame_matches_static"]
                or not frames
                or digest(frames[-1]) != digest(folder / "static.png")
            ):
                raise RuntimeError("Replay final frame differs from static")
            export = queue.submit_export(job["id"], [10, 12, 80, 90], 4)
            wait_job(queue, export["id"])
            out = queue.root / export["id"] / "output"
            result = json.loads((out / "manifest.json").read_text())
            forward = sorted((out / "frames").glob("*.png"))
            loop = sorted((out / "video-frames").glob("*.png"))
            if (
                not result["forward_final_frame_matches_static"]
                or not result["loop_seam_matches"]
                or not loop
                or digest(forward[-1]) != digest(out / "static.png")
                or digest(loop[0]) != digest(loop[-1])
                or not (out / "replay.mp4").stat().st_size
            ):
                raise RuntimeError("Crop/loop verification failed")
            status, range_headers, first_bytes = request(
                server.server_port,
                f"/media/{export['id']}/replay.mp4",
                {"Cookie": cookie, "Range": "bytes=0-15"},
            )
            if (
                status != 206
                or len(first_bytes) != 16
                or not range_headers.get("Content-Range", "").startswith("bytes 0-15/")
                or first_bytes != (out / "replay.mp4").read_bytes()[:16]
            ):
                raise RuntimeError("Installed video range serving failed")
            print(
                json.dumps(
                    {
                        "package": str(package),
                        "python": sys.executable,
                        "http": {"session": True, "assets": True, "video_range": True},
                        "replay": {"final_frame_matches_static": True, "frames": len(frames)},
                        "export": {
                            "forward_final_frame_matches_static": True,
                            "loop_seam_matches": True,
                            "frames": len(loop),
                        },
                    },
                    indent=2,
                )
            )
        finally:
            server.shutdown()
            server.server_close()
            server.app.jobs.close()
            thread.join()


if __name__ == "__main__":
    main()
