"""CLI entrypoint."""
from __future__ import annotations

import argparse

from nirip.cli.commands import cmd_apply, cmd_capture, cmd_diff, cmd_plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nirip")
    sub = parser.add_subparsers(dest="command", required=True)

    for cmd in ["apply", "diff", "plan"]:
        p = sub.add_parser(cmd)
        p.add_argument("session_file")

    p_capture = sub.add_parser("capture")
    p_capture.add_argument("-o", "--output", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "apply":
        print(cmd_apply(args.session_file))
    elif args.command == "diff":
        print(cmd_diff(args.session_file))
    elif args.command == "plan":
        print(cmd_plan(args.session_file))
    elif args.command == "capture":
        print(cmd_capture(args.output))
    else:
        parser.error(f"Unknown command: {args.command}")

    return 0
