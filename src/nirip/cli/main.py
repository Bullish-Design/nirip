"""CLI entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nirip", description="Niri session manager")
    sub = parser.add_subparsers(dest="command")

    p_apply = sub.add_parser("apply", help="Apply a session spec")
    p_apply.add_argument("session_file")
    p_apply.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    p_apply.add_argument("--dry-run", action="store_true", help="Show plan without executing")

    p_diff = sub.add_parser("diff", help="Show what would change")
    p_diff.add_argument("session_file")

    p_plan = sub.add_parser("plan", help="Show execution plan")
    p_plan.add_argument("session_file")

    p_capture = sub.add_parser("capture", help="Capture current state")
    p_capture.add_argument("-o", "--output", help="Write to file")
    p_capture.add_argument("-n", "--name", help="Session name")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    from nirip.cli.commands import cmd_apply, cmd_capture, cmd_diff, cmd_plan

    try:
        if args.command == "apply":
            output = asyncio.run(cmd_apply(args.session_file, yes=args.yes, dry_run=args.dry_run))
        elif args.command == "diff":
            output = asyncio.run(cmd_diff(args.session_file))
        elif args.command == "plan":
            output = asyncio.run(cmd_plan(args.session_file))
        elif args.command == "capture":
            output = asyncio.run(cmd_capture(name=args.name, output=args.output))
        else:
            parser.print_help()
            return 1
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(output)
    return 0
