"""nirip: Declarative session reconciler for Niri."""

from __future__ import annotations

import asyncio
from pathlib import Path

from nirip.config import NiripConfig
from nirip.execution.models import ApplyResult
from nirip.facade.async_nirip import AsyncNirip
from nirip.planning.models import Plan, SessionDiff
from nirip.spec.loader import load_spec_from_dict, load_spec_from_file, load_spec_from_string
from nirip.spec.models import SessionSpec
from nirip.spec.validators import ValidatedSpec

__all__ = [
    "ApplyResult",
    "AsyncNirip",
    "NiripConfig",
    "Plan",
    "SessionSpec",
    "SessionDiff",
    "ValidatedSpec",
    "apply_session",
    "diff_session",
    "load_session",
    "load_spec_from_dict",
    "load_spec_from_file",
    "load_spec_from_string",
    "plan_session",
]


def load_session(path: str | Path) -> ValidatedSpec:
    return load_spec_from_file(path)


def apply_session(spec: SessionSpec, config: NiripConfig | None = None) -> ApplyResult:
    async def _run() -> ApplyResult:
        async with await AsyncNirip.open(config) as nirip:
            return await nirip.apply(spec)

    return asyncio.run(_run())


def plan_session(spec: SessionSpec, config: NiripConfig | None = None) -> Plan:
    """One-shot sync plan."""

    async def _run() -> Plan:
        async with await AsyncNirip.open(config) as nirip:
            return await nirip.plan(spec)

    return asyncio.run(_run())


def diff_session(spec: SessionSpec, config: NiripConfig | None = None) -> SessionDiff:
    """One-shot sync diff."""

    async def _run() -> SessionDiff:
        async with await AsyncNirip.open(config) as nirip:
            return await nirip.diff(spec)

    return asyncio.run(_run())
