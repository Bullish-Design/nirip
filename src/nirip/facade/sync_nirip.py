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
        self._async: AsyncNirip | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _ensure_async(self) -> AsyncNirip:
        if self._async is None:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
            self._async = self._loop.run_until_complete(AsyncNirip.open(self._config))
            if self._snapshot is not None:
                self._async.bind_snapshot(self._snapshot)
        return self._async

    def bind_snapshot(self, snapshot: Any) -> None:
        self._snapshot = snapshot
        if self._async is not None:
            self._async.bind_snapshot(snapshot)

    def diff(self, spec: SessionSpec) -> SessionDiff:
        async_nirip = self._ensure_async()
        assert self._loop is not None
        return self._loop.run_until_complete(async_nirip.diff(spec))

    def plan(self, spec: SessionSpec) -> Plan:
        async_nirip = self._ensure_async()
        assert self._loop is not None
        return self._loop.run_until_complete(async_nirip.plan(spec))

    def apply(self, spec: SessionSpec) -> ApplyResult:
        async_nirip = self._ensure_async()
        assert self._loop is not None
        return self._loop.run_until_complete(async_nirip.apply(spec))

    def capture(self, *, name: str | None = None) -> CapturedSession:
        async_nirip = self._ensure_async()
        assert self._loop is not None
        return self._loop.run_until_complete(async_nirip.capture(name=name))

    def close(self) -> None:
        if self._async is not None and self._loop is not None:
            self._loop.run_until_complete(self._async.close())
            self._async = None
        if self._loop is not None:
            self._loop.close()
            self._loop = None

    def __enter__(self) -> SyncNirip:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
