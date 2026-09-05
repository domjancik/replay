from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from .adapter import dump_page_json, parse_page


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dump a normalized reMarkable v6 page")
    parser.add_argument("source", type=Path, help="path to a v6 .rm page")
    parser.add_argument("--page-id", help="stable page ID; defaults to the source filename")
    parser.add_argument("--output", type=Path, help="write JSON to this path instead of stdout")
    parser.add_argument(
        "--replay-strategy",
        choices=("crdt-order", "scene-order"),
        default="crdt-order",
        help="deterministic fallback ordering; neither choice claims drawing chronology",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    page = parse_page(
        args.source,
        page_id=args.page_id,
        replay_strategy=args.replay_strategy,
    )
    encoded = dump_page_json(page, args.output)
    if args.output is None:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
