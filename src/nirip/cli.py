"""CLI entry point, commands, and formatting."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import yaml

from nirip.execute import ApplyResult, SessionPorts, execute_plan
from nirip.plan import Plan, build_plan
from nirip.resolve import Resolution, ResolutionStatus, resolve
from nirip.spec import NiripError, load_from_file


def format_resolution(resolution: Resolution) -> str:
    """Human-readable summary of what would change."""
    if resolution.fully_converged:
        return "No changes needed — session is converged."

    lines: list[str] = []

    matched = [ar for ar in resolution.apps if ar.status == ResolutionStatus.MATCHED]
    if matched:
        lines.append(f"Matched: {len(matched)} app(s)")

    will_spawn = [ar for ar in resolution.apps if ar.status == ResolutionStatus.MISSING]
    if will_spawn:
        lines.append("Will spawn:")
        for ar in will_spawn:
            lines.append(f"  + {ar.workspace_name}/{ar.app_name}")

    optional = [ar for ar in resolution.apps if ar.status == ResolutionStatus.OPTIONAL_MISSING]
    if optional:
        lines.append(f"Optional (not running): {len(optional)}")
        for ar in optional:
            lines.append(f"  ? {ar.workspace_name}/{ar.app_name}")

    will_move: list[str] = []
    drifted: list[str] = []
    errors: list[str] = []
    for ar in resolution.apps:
        label = f"{ar.workspace_name}/{ar.app_name}"
        if ar.status == ResolutionStatus.DRIFTED:
            if ar.needs_move:
                will_move.append(label)
            if any(d.kind.value != "wrong_workspace" for d in ar.drift):
                drifted.append(label)
        elif ar.status == ResolutionStatus.AMBIGUOUS:
            errors.append(f"ambiguous match: {label}")

    if will_move:
        lines.append("Will move:")
        for app in will_move:
            lines.append(f"  ~ {app}")

    if drifted:
        lines.append("Drifted:")
        for app in drifted:
            lines.append(f"  * {app}")

    workspace_changes: list[str] = []
    for ws in resolution.workspaces:
        if not ws.exists:
            workspace_changes.append(f"workspace '{ws.name}' will be created")
        elif ws.desired_output and not ws.output_correct:
            workspace_changes.append(
                f"workspace '{ws.name}' will move output {ws.current_output} -> {ws.desired_output}"
            )
    if workspace_changes:
        lines.append("Workspace changes:")
        for change in workspace_changes:
            lines.append(f"  {change}")

    if errors:
        lines.append("Errors:")
        for err in errors:
            lines.append(f"  ! {err}")

    return "\n".join(lines)


def format_plan(plan: Plan) -> str:
    if plan.is_empty:
        return "Empty plan — nothing to do."
    lines = [f"Plan: {len(plan.steps)} step(s)"]
    for i, step in enumerate(plan.steps, 1):
        deps = f" (after: {', '.join(step.depends_on)})" if step.depends_on else ""
        lines.append(f"  {i}. [{step.kind}] {step.description}{deps}")
    return "\n".join(lines)


def format_result(result: ApplyResult) -> str:
    status = "SUCCESS" if result.success else "FAILED"
    lines = [f"Result: {status} ({result.total_duration_s:.1f}s)"]
    lines.append(f"  Completed: {result.completed_count}, Skipped: {result.skipped_count}")
    if result.failed_steps:
        lines.append("  Failed steps:")
        for fs in result.failed_steps:
            lines.append(f"    - {fs.step.description}: {fs.message}")
    return "\n".join(lines)


class LoggingHook:
    def on_step_start(self, step) -> None:
        print(f"  -> {step.description}...", file=sys.stderr, flush=True)

    def on_step_complete(self, step, result) -> None:
        del step
        print(f"     {result.outcome} ({result.duration_s:.1f}s)", file=sys.stderr, flush=True)

    def on_plan_complete(self, result) -> None:
        status = "OK" if result.success else "FAILED"
        print(f"  Plan {status} in {result.total_duration_s:.1f}s", file=sys.stderr, flush=True)


async def cmd_apply(session_file: str, *, yes: bool = False, dry_run: bool = False, quiet: bool = False) -> str:
    spec, validation = load_from_file(session_file)
    for w in validation.warnings:
        print(f"  warning: {w}", file=sys.stderr)

    from niri_pypc import NiriClient
    from niri_state import NiriState

    state = await NiriState.open()
    client = NiriClient.create()
    ports = SessionPorts(state=state, client=client)
    try:
        resolution = resolve(spec, state.snapshot)
        if dry_run:
            plan = build_plan(resolution, spec.options)
            return format_plan(plan)

        if not yes and resolution.has_drift:
            print(format_resolution(resolution), file=sys.stderr)
            answer = await asyncio.to_thread(input, "Apply? [y/N] ")
            if answer.lower() != "y":
                return "Aborted."

        plan = build_plan(resolution, spec.options)
        if plan.is_empty:
            return "Nothing to do."

        hook = None if quiet else LoggingHook()
        result = await execute_plan(plan, ports, spec.options, hook=hook)
        return format_result(result)
    finally:
        await state.close()
        await client.close()


async def cmd_diff(session_file: str) -> str:
    spec, _ = load_from_file(session_file)
    from niri_state import NiriState

    state = await NiriState.open()
    try:
        resolution = resolve(spec, state.snapshot)
        return format_resolution(resolution)
    finally:
        await state.close()


async def cmd_plan(session_file: str) -> str:
    spec, _ = load_from_file(session_file)
    from niri_state import NiriState

    state = await NiriState.open()
    try:
        resolution = resolve(spec, state.snapshot)
        plan = build_plan(resolution, spec.options)
        return format_plan(plan)
    finally:
        await state.close()


async def cmd_capture(*, name: str | None = None, output: str | None = None) -> str:
    from niri_state import NiriState

    from nirip.capture import capture

    state = await NiriState.open()
    try:
        spec = capture(state.snapshot, name=name)
        text = yaml.dump(spec.model_dump(), default_flow_style=False)
        if output:
            Path(output).write_text(text, encoding="utf-8")
        return text
    finally:
        await state.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nirip", description="Niri session manager")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show full traceback on error")
    sub = parser.add_subparsers(dest="command")

    p_apply = sub.add_parser("apply", help="Apply a session spec")
    p_apply.add_argument("session_file")
    p_apply.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    p_apply.add_argument("--dry-run", action="store_true", help="Show plan without executing")
    p_apply.add_argument("-q", "--quiet", action="store_true", help="Suppress live apply progress")

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

    try:
        match args.command:
            case "apply":
                output = asyncio.run(cmd_apply(args.session_file, yes=args.yes, dry_run=args.dry_run, quiet=args.quiet))
            case "diff":
                output = asyncio.run(cmd_diff(args.session_file))
            case "plan":
                output = asyncio.run(cmd_plan(args.session_file))
            case "capture":
                output = asyncio.run(cmd_capture(name=args.name, output=args.output))
            case _:
                parser.print_help()
                return 1
    except Exception as e:
        if args.verbose:
            import traceback

            traceback.print_exc(file=sys.stderr)
        else:
            print(f"error: {e}", file=sys.stderr)
        return 1

    print(output)
    return 0
