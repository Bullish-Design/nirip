"""Synchronous wrapper."""

from __future__ import annotations

import asyncio
from typing import Any

from niri_pypc import NiriClient
from niri_state import NiriState

from nirip.capture.capturer import CapturedSession
from nirip.config import NiripConfig
from nirip.execution.models import ApplyResult
from nirip.facade.async_nirip import AsyncNirip
from nirip.planning.models import Plan, SessionDiff
from nirip.spec.models import SessionSpec


class SyncNirip:
    def __init__(self, *, state: NiriState, client: NiriClient, config: NiripConfig | None = None) -> None:
        self._async = AsyncNirip(state=state, client=client, config=config)

    @classmethod
    def open(cls, config: NiripConfig | None = None) -> "SyncNirip":
        state = asyncio.run(NiriState.open())
        client = NiriClient.create()
        return cls(state=state, client=client, config=config)

    def diff(self, spec: SessionSpec) -> SessionDiff:
        return asyncio.run(self._async.diff(spec))

    def plan(self, spec: SessionSpec) -> Plan:
        return asyncio.run(self._async.plan(spec))

    def apply(self, spec: SessionSpec) -> ApplyResult:
        return asyncio.run(self._async.apply(spec))

    def capture(self, *, name: str | None = None) -> CapturedSession:
        return asyncio.run(self._async.capture(name=name))

    def close(self) -> None:
        asyncio.run(self._async.close())

    def __enter__(self) -> "SyncNirip":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()
