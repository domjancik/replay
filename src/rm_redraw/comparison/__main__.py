from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .command import ComparisonError, run_comparison


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare a local candidate PNG with a native PNG or PDF"
    )
    parser.add_argument("candidate", type=Path, help="candidate PNG; no tablet connection")
    native = parser.add_mutually_exclusive_group(required=True)
    native.add_argument("--native-png", type=Path)
    native.add_argument("--native-pdf", type=Path)
    parser.add_argument("--page", type=int, default=1, help="one-based native PDF page number")
    parser.add_argument(
        "--ink-only",
        action="store_true",
        help="remove direct typed-text PDF objects before comparing native ink",
    )
    parser.add_argument("--output", type=Path, required=True, help="new output directory")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run_comparison(
            args.candidate,
            native_png=args.native_png,
            native_pdf=args.native_pdf,
            page=args.page,
            ink_only=args.ink_only,
            output_directory=args.output,
        )
    except ComparisonError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(result.output_directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
