"""Pure replay settings validation shared by desktop and browser hosts."""


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
    output = number("output_width", 128, 2808, integer=True)
    output += output % 2
    out_height = max(2, round(output * height / width / 2) * 2)
    if output * out_height > 12_000_000:
        raise ValueError("Output exceeds the 12 megapixel limit; reduce output width")
    if out_height > 8192:
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
