import pytest

from rm_redraw.rendering.types import RenderOptions


def test_pencil_backend_default_and_selection():
    assert RenderOptions().pencil_backend == "python"
    assert RenderOptions(pencil_backend="rust") != RenderOptions()


@pytest.mark.parametrize(
    "kwargs", [{"pencil_backend": "unknown"}, {"pencil_backend": "rust", "pencil_boundary": True}]
)
def test_invalid_pencil_backend(kwargs):
    with pytest.raises(ValueError, match="pencil"):
        RenderOptions(**kwargs)
