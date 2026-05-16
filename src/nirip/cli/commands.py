"""CLI command handlers."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from nirip.facade.async_nirip import AsyncNirip
from nirip.spec.loader import load_spec_from_file


async def cmd_apply(session_file: str, *, yes: bool = False) -> str:
    validated = load_spec_from_file(session_file)
    for w in validated.validation.warnings:
        print(f"  warning: {w}", file=sys.stderr)

    async with await AsyncNirip.open() as nirip:
        if not yes:
            diff = await nirip.diff(validated.spec)
            text = yaml.dump(diff.model_dump(), default_flow_style=False)
            print(text, file=sys.stderr)
            if diff.has_drift:
                answer = input("Apply? [y/N] ")
                if answer.lower() != "y":
                    return "aborted"

        result = await nirip.apply(validated.spec)
        return yaml.dump(result.model_dump(), default_flow_style=False)


async def cmd_diff(session_file: str) -> str:
    validated = load_spec_from_file(session_file)
    async with await AsyncNirip.open() as nirip:
        diff = await nirip.diff(validated.spec)
        return yaml.dump(diff.model_dump(), default_flow_style=False)


async def cmd_plan(session_file: str) -> str:
    validated = load_spec_from_file(session_file)
    async with await AsyncNirip.open() as nirip:
        plan = await nirip.plan(validated.spec)
        return yaml.dump(plan.model_dump(), default_flow_style=False)


async def cmd_capture(*, name: str | None = None, output: str | None = None) -> str:
    async with await AsyncNirip.open() as nirip:
        captured = await nirip.capture(name=name)
        text = yaml.dump(captured.spec.model_dump(), default_flow_style=False)
        if output:
            Path(output).write_text(text, encoding="utf-8")
        return text
