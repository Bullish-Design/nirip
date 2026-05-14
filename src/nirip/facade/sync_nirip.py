"""Sync nirip facade."""
from __future__ import annotations

import asyncio
from typing import Any

from nirip.capture.capturer import CapturedSession
from nirip.config import NiripConfig
from nirip.execution.models import ApplyResult
from nirip.facade.async_nirip import AsyncNirip
from nirip.planning.models import Plan, SessionDiff
from nirip.spec.models import SessionSpec


class SyncNirip:
    """Thin sync wrapper."""

    def __init__(self, config: NiripConfig | None = None) -> None:
        self._config = config
        self._snapshot: Any | None = None

    def bind_snapshot(self, snapshot: Any) -> None:
        self._snapshot = snapshot

    def _run(self, coro):
        return asyncio.run(coro)

    def diff(self, spec: SessionSpec) -> SessionDiff:
        async def _inner() -> SessionDiff:
            nirip = await AsyncNirip.open(self._config)
            nirip.bind_snapshot(self._snapshot)
            return await nirip.diff(spec)

        return self._run(_inner())

    def plan(self, spec: SessionSpec) -> Plan:
        async def _inner() -> Plan:
            nirip = await AsyncNirip.open(self._config)
            nirip.bind_snapshot(self._snapshot)
            return await nirip.plan(spec)

        return self._run(_inner())

    def apply(self, spec: SessionSpec) -> ApplyResult:
        async def _inner() -> ApplyResult:
            nirip = await AsyncNirip.open(self._config)
            nirip.bind_snapshot(self._snapshot)
            return await nirip.apply(spec)

        return self._run(_inner())

    def capture(self, *, name: str | None = None) -> CapturedSession:
        async def _inner() -> CapturedSession:
            nirip = await AsyncNirip.open(self._config)
            nirip.bind_snapshot(self._snapshot)
            return await nirip.capture(name=name)

        return self._run(_inner())

    def close(self) -> None:
        return None

    def __enter__(self) -> SyncNirip:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
