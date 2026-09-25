from dataclasses import replace

import numpy as np

from rm_redraw.rendering import PillowRenderer
from rm_redraw.rendering.types import (
    NormalizedGroup,
    NormalizedPage,
    NormalizedPoint,
    NormalizedStroke,
    RenderOptions,
    VisibilityState,
)


def _page():
    stroke = NormalizedStroke(
        "calligraphy",
        "ink",
        (40, 80, 120, 128),
        2,
        tuple(
            NormalizedPoint(x, y, 128, 30, 64, 40)
            for x, y in [(12.25, 16.75), (45.25, 36.75), (79.25, 54.75)]
        ),
        tool_code=21,
    )
    return NormalizedPage(
        "aa",
        (96, 72),
        (NormalizedGroup("ink"),),
        (stroke,),
        ("ink",),
        ("calligraphy",),
        "scene-order",
        "synthetic",
    )


def test_calligraphy_dispatch_antialiases_without_reapplying_source_alpha():
    options = RenderOptions(background=(0, 0, 0, 0))
    image = PillowRenderer().render_static(_page(), options)
    alpha = np.asarray(image)[:, :, 3]
    assert np.any((alpha > 0) & (alpha < 128))
    assert alpha.max() == 128


def test_calligraphy_cached_reveal_matches_stateless_and_preserves_completed_prefix():
    page, renderer = _page(), PillowRenderer()
    options = RenderOptions()
    frames = []
    for progress in (0.4, 0.8, 1.0, 0.2):
        state = VisibilityState(active_stroke_id="calligraphy", active_progress=progress)
        frame = renderer.render(page, options, state)
        assert frame.tobytes() == renderer._render_uncached(page, options, state).tobytes()
        frames.append(frame)
    assert frames[0].crop((0, 0, 25, 72)).tobytes() == frames[1].crop((0, 0, 25, 72)).tobytes()
    assert frames[2].tobytes() == renderer.render_static(page, options).tobytes()
    assert frames[0].getpixel((79, 55)) == (255, 255, 255, 255)
    named = replace(
        page, strokes=(replace(page.strokes[0], tool_code=None, tool_name="CALIGRAPHY"),)
    )
    assert renderer.render_static(named, options).tobytes() == frames[2].tobytes()
