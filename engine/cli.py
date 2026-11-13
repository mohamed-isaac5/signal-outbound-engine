"""`soe` command line: the engine's one-entry-point interface."""

from __future__ import annotations

import argparse

from engine import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="soe",
        description="Signal-driven outbound engine.",
    )
    parser.add_argument("--version", action="store_true", help="print version and exit")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("score", help="score signals against the ICP (M1)")
    sub.add_parser("enrich", help="run the enrichment waterfall (M2)")
    sub.add_parser("draft", help="draft outreach from approved fits (M3)")
    sub.add_parser("approve", help="review the approval queue (M4)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    if args.command is None:
        parser.print_help()
        return 0
    print(f"`soe {args.command}` lands in a later milestone - see README roadmap.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
