"""nirip: Declarative session reconciler for Niri."""

from __future__ import annotations

import asyncio
from pathlib import Path

from nirip.config import NiripConfig
from nirip.execution.models import ApplyResult
from nirip.facade.async_nirip import AsyncNirip
from nirip.facade.sync_nirip import SyncNirip
from nirip.spec.loader import load_spec_from_dict, load_spec_from_file, load_spec_from_string
from nirip.spec.models import SessionSpec
from nirip.spec.validators import ValidatedSpec

__all__ = [
    "ApplyResult",
    "AsyncNirip",
    "NiripConfig",
    "SessionSpec",
    "SyncNirip",
    "ValidatedSpec",
    "apply_session",
    "load_session",
    "load_spec_from_dict",
    "load_spec_from_file",
    "load_spec_from_string",
]


def load_session(path: str | Path) -> ValidatedSpec:
    return load_spec_from_file(path)


def apply_session(spec: SessionSpec) -> ApplyResult:
    async def _run() -> ApplyResult:
        async with await AsyncNirip.open() as nirip:
            return await nirip.apply(spec)

    return asyncio.run(_run())
