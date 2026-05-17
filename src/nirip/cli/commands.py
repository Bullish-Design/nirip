"""CLI command handlers."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import yaml

from nirip.cli.formatting import format_diff, format_plan, format_result
from nirip.facade.async_nirip import AsyncNirip
from nirip.spec.loader import load_spec_from_file


async def cmd_apply(session_file: str, *, yes: bool = False, dry_run: bool = False) -> str:
    validated = load_spec_from_file(session_file)
    for w in validated.validation.warnings:
        print(f"  warning: {w}", file=sys.stderr)

    async with await AsyncNirip.open() as nirip:
        if dry_run:
            plan = await nirip.plan(validated.spec)
            return format_plan(plan)

        if not yes:
            diff = await nirip.diff(validated.spec)
            print(format_diff(diff), file=sys.stderr)
            if diff.has_drift:
                answer = await asyncio.to_thread(input, "Apply? [y/N] ")
                if answer.lower() != "y":
                    return "Aborted."

        result = await nirip.apply(validated.spec)
        return format_result(result)


async def cmd_diff(session_file: str) -> str:
    validated = load_spec_from_file(session_file)
    async with await AsyncNirip.open() as nirip:
        diff = await nirip.diff(validated.spec)
        return format_diff(diff)


async def cmd_plan(session_file: str) -> str:
    validated = load_spec_from_file(session_file)
    async with await AsyncNirip.open() as nirip:
        plan = await nirip.plan(validated.spec)
        return format_plan(plan)


async def cmd_capture(*, name: str | None = None, output: str | None = None) -> str:
    async with await AsyncNirip.open() as nirip:
        captured = await nirip.capture(name=name)
        text = yaml.dump(captured.spec.model_dump(), default_flow_style=False)
        if output:
            Path(output).write_text(text, encoding="utf-8")
        return text
