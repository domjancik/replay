import pytest

from rm_redraw.web.jobs import validate_settings


def test_settings_limit_work_and_keep_explicit_geometry():
    result = validate_settings(
        {
            "width": 1404,
            "height": 1872,
            "offset_x": 702,
            "offset_y": 0,
            "seconds": 10,
            "fps": 12,
            "output_width": 702,
            "backend": "python",
        }
    )
    assert result["viewport"] == (702, 936)
    assert result["source_affine"] == (1, 0, 0, 1, 702, 0)


@pytest.mark.parametrize(
    "key,value",
    [
        ("width", 999999),
        ("seconds", float("nan")),
        ("fps", 0),
        ("backend", "shell"),
        ("offset_y", float("inf")),
    ],
)
def test_invalid_settings(key, value):
    settings = {
        "width": 1404,
        "height": 1872,
        "offset_x": 702,
        "offset_y": 0,
        "seconds": 10,
        "fps": 12,
        "output_width": 702,
        "backend": "python",
    }
    settings[key] = value
    with pytest.raises(ValueError):
        validate_settings(settings)


def test_real_job_completion_and_history(tmp_path):
    import json
    import time
    from io import BytesIO
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

    from rm_redraw.web.jobs import Jobs
    from rm_redraw.web.library import Library

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
    library = Library(tmp_path / "library")
    document = library.add(archive.getvalue(), provenance={"provider": "test"})
    queue = Jobs(tmp_path / "jobs", library)
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
    try:
        settings["offset_y"] = 32
        with pytest.raises(ValueError, match="outside the selected canvas"):
            queue.submit(document["id"], "page", settings)
        assert queue.list() == []
        settings["allow_clipping"] = True
        job = queue.submit(document["id"], "page", settings)
        assert job["settings"]["allow_clipping"] is True
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            status = queue.list()[0]
            if status["state"] not in ("queued", "running"):
                break
            time.sleep(0.05)
        assert status["state"] == "complete", status
        assert status["frames"] == 18
        manifest = json.loads(queue.media(job["id"], "manifest.json").read_text())
        assert manifest["final_frame_matches_static"]
        assert manifest["replay"]["mode"] == "duration"
        assert manifest["replay"]["ordering"] == "entry"
        assert queue.media(job["id"], "replay.mp4").stat().st_size > 0
        exported = queue.submit_export(job["id"], [10, 12, 80, 90], 4)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            status = queue.list()[0]
            if status["state"] not in ("queued", "running"):
                break
            time.sleep(0.05)
        assert status["id"] == exported["id"]
        assert status["state"] == "complete", status
        manifest = json.loads(queue.media(exported["id"], "manifest.json").read_text())
        assert manifest["viewport"] == {"width": 80, "height": 90}
        assert manifest["forward_final_frame_matches_static"]
        assert manifest["loop_seam_matches"]
        assert status["frames"] == manifest["frame_count"] > 18
        with pytest.raises(ValueError, match="original replay"):
            queue.submit_export(exported["id"], None, 4)
    finally:
        queue.close()
    reopened = Jobs(tmp_path / "jobs", library)
    try:
        assert reopened.list()[0]["state"] == "complete"
    finally:
        reopened.close()


def test_cancelled_queue_entry_never_starts_and_interrupted_jobs_stay_stopped(
    tmp_path, monkeypatch
):
    import json

    from rm_redraw.web.jobs import Jobs
    from rm_redraw.web.library import Library

    queue = Jobs(tmp_path / "jobs", Library(tmp_path / "library"))
    job = {"id": "a" * 32, "state": "queued", "created": 1}
    queue.jobs[job["id"]] = job
    queue._save(job)

    def forbidden(*args, **kwargs):
        raise AssertionError("Cancelled job launched a subprocess")

    monkeypatch.setattr("rm_redraw.web.jobs.subprocess.Popen", forbidden)
    try:
        queue.cancel(job["id"])
        queue._run(job["id"])
        assert queue.list()[0]["state"] == "cancelled"
    finally:
        queue.close()
    path = tmp_path / "jobs" / ("b" * 32)
    path.mkdir()
    (path / "job.json").write_text(json.dumps({"id": "b" * 32, "state": "running", "created": 2}))
    reopened = Jobs(tmp_path / "jobs", Library(tmp_path / "library"))
    try:
        assert reopened.list()[0]["state"] == "interrupted"
        assert json.loads((path / "job.json").read_text())["state"] == "interrupted"
    finally:
        reopened.close()


def test_bad_history_does_not_prevent_startup(tmp_path):
    import json

    from rm_redraw.web.jobs import Jobs
    from rm_redraw.web.library import Library

    root = tmp_path / "jobs"
    bad = root / ("a" * 32)
    bad.mkdir(parents=True)
    record = bad / "job.json"
    record.write_text("{", encoding="utf-8")
    good = root / ("b" * 32)
    good.mkdir()
    good_record = {"id": good.name, "state": "cancelled", "created": 1}
    (good / "job.json").write_text(json.dumps(good_record), encoding="utf-8")
    queue = Jobs(root, Library(tmp_path / "library"))
    try:
        assert [job["id"] for job in queue.list()] == [good.name]
        assert record.read_text(encoding="utf-8") == "{"
    finally:
        queue.close()


def test_failed_running_status_write_releases_queue_slot(tmp_path, monkeypatch):
    from rm_redraw.web.jobs import Jobs
    from rm_redraw.web.library import Library

    queue = Jobs(tmp_path / "jobs", Library(tmp_path / "library"))
    job = {"id": "a" * 32, "state": "queued", "created": 1}
    queue.jobs[job["id"]] = job
    queue._save(job)

    def storage_unavailable(job):
        raise OSError("Test storage unavailable")

    monkeypatch.setattr(queue, "_save", storage_unavailable)
    try:
        queue._run(job["id"])
        result = queue.list()[0]
        assert result["state"] == "failed"
        assert "Test storage unavailable" in result["error"]
    finally:
        queue.close()
