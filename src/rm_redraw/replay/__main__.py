from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .command import ReplayCommandError, run_local_replay


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay one local reMarkable .rm page or .rmdoc archive"
    )
    parser.add_argument(
        "source", type=Path, help="local .rm page or .rmdoc archive; no tablet connection"
    )
    parser.add_argument("--output", type=Path, required=True, help="new output directory")
    parser.add_argument("--page-id", help="required for multi-page .rmdoc archives")
    parser.add_argument("--paper-size", type=int, nargs=2, metavar=("WIDTH", "HEIGHT"))
    parser.add_argument(
        "--source-affine",
        type=float,
        nargs=6,
        metavar=("A", "B", "C", "D", "E", "F"),
        help="source-to-page affine transform override",
    )
    parser.add_argument(
        "--paired-native-pdf",
        type=Path,
        help="local paired native PDF to hash and validate as export evidence",
    )
    parser.add_argument(
        "--paired-pdf-page",
        type=int,
        default=1,
        help="one-based paired native PDF page (default: 1)",
    )
    parser.add_argument(
        "--export-canvas",
        type=int,
        nargs=2,
        metavar=("WIDTH", "HEIGHT"),
        help="caller-validated target canvas; does not infer DPI or device scale",
    )
    parser.add_argument(
        "--mode",
        choices=("stroke-step", "seconds-per-stroke", "distance-per-second"),
        default="stroke-step",
    )
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--seconds-per-stroke", type=float)
    parser.add_argument("--distance-per-second", type=float)
    parser.add_argument("--viewport", type=int, nargs=2, metavar=("WIDTH", "HEIGHT"))
    parser.add_argument(
        "--replay-strategy",
        choices=("crdt-order", "scene-order"),
        default="crdt-order",
        help="deterministic fallback order; neither choice claims chronology",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run_local_replay(
            args.source,
            output_directory=args.output,
            page_id=args.page_id,
            paper_size=tuple(args.paper_size) if args.paper_size is not None else None,
            source_affine=tuple(args.source_affine) if args.source_affine is not None else None,
            paired_native_pdf=args.paired_native_pdf,
            paired_pdf_page=args.paired_pdf_page,
            export_canvas=tuple(args.export_canvas) if args.export_canvas is not None else None,
            mode=args.mode,
            fps=args.fps,
            seconds_per_stroke=args.seconds_per_stroke,
            distance_per_second=args.distance_per_second,
            viewport=tuple(args.viewport) if args.viewport is not None else None,
            replay_strategy=args.replay_strategy,
        )
    except ReplayCommandError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(result.output_directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
