import importlib.util
import runpy
from pathlib import Path


def test_browser_bridge_legacy_normalizes_and_schedules():
    spec = importlib.util.spec_from_file_location("bridge", Path("native/hosted/bridge.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    raw = runpy.run_path("tests/parsing/test_legacy_v5.py")["legacy_page"]()
    result = module.prepare(
        raw,
        "page",
        dict(
            width=1404,
            height=1872,
            offset_x=0,
            offset_y=0,
            seconds=2,
            fps=6,
            output_width=2808,
            backend="rust",
        ),
    )
    assert result["request"]["options"]["viewport"] == {"width": 2808, "height": 3744}
    assert result["request"]["page"]["strokes"][0]["points"][0]["x"] == 20
    assert result["frames"][-1]["active_stroke_id"] is None
    assert result["frames"][-1]["completed_stroke_ids"]


def test_browser_bridge_rejects_unacknowledged_clipping():
    import pytest

    spec = importlib.util.spec_from_file_location("bridge", Path("native/hosted/bridge.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    raw = runpy.run_path("tests/parsing/test_legacy_v5.py")["legacy_page"]()
    with pytest.raises(ValueError, match="outside the selected canvas"):
        module.prepare(
            raw,
            "page",
            dict(
                width=64,
                height=64,
                offset_x=0,
                offset_y=0,
                seconds=2,
                fps=6,
                output_width=128,
                backend="rust",
            ),
        )


def test_browser_bridge_refuses_unresolved_native_text_anchors(monkeypatch):
    from types import SimpleNamespace

    import pytest

    spec = importlib.util.spec_from_file_location("bridge", Path("native/hosted/bridge.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module,
        "parse_page",
        lambda *a, **kw: SimpleNamespace(
            strokes=[SimpleNamespace(effective_transform=SimpleNamespace(resolved=False))]
        ),
    )
    with pytest.raises(ValueError, match="text-anchor"):
        module.prepare(
            b"",
            "page",
            dict(
                width=64,
                height=64,
                offset_x=0,
                offset_y=0,
                seconds=2,
                fps=6,
                output_width=128,
                backend="rust",
            ),
        )


def test_browser_anchor_results_reject_conflicting_shared_offsets():
    import pytest

    spec = importlib.util.spec_from_file_location("bridge", Path("native/hosted/bridge.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plan = {
        "root_y": 234,
        "page_y": 0,
        "templates": [
            {"anchor_id": "1:17", "group_id": "1:100", "parent_y": 0},
            {"anchor_id": "1:17", "group_id": "1:200", "parent_y": 0},
        ],
    }
    fits = [{"accepted": True, "best_candidate": {"translation_y": y}} for y in (500, 600)]
    with pytest.raises(ValueError, match="conflicting-shared-anchor"):
        module.resolve_anchor_fits(plan, fits)
    fits[1] = fits[0]
    assert module.resolve_anchor_fits(plan, fits) == {"1:17": 266}
