"""Primary async API."""

from __future__ import annotations

from typing import Any

from niri_pypc import NiriClient
from niri_state import HealthState, NiriState, Snapshot

from nirip.capture.capturer import CapturedSession, capture_from_snapshot
from nirip.config import NiripConfig
from nirip.execution.executor import execute_plan
from nirip.execution.models import ApplyResult, SessionPorts
from nirip.planning.compiler import compile_diff, compile_plan
from nirip.planning.models import Plan, SessionDiff
from nirip.resolve.normalizer import normalize
from nirip.resolve.resolver import resolve
from nirip.spec.models import SessionSpec


class AsyncNirip:
    """Async API owning real NiriState + NiriClient connections."""

    def __init__(self, *, state: NiriState, client: NiriClient, config: NiripConfig | None = None) -> None:
        self._state = state
        self._client = client
        self._config = config or NiripConfig()

    @classmethod
    async def open(cls, config: NiripConfig | None = None) -> AsyncNirip:
        state = await NiriState.open()
        client = NiriClient.create()
        return cls(state=state, client=client, config=config)

    @property
    def snapshot(self) -> Snapshot:
        return self._state.snapshot

    @property
    def health(self) -> HealthState:
        return self._state.health()

    async def diff(self, spec: SessionSpec) -> SessionDiff:
        normalized = normalize(spec)
        resolution = resolve(normalized, self.snapshot)
        return compile_diff(resolution)

    async def plan(self, spec: SessionSpec) -> Plan:
        normalized = normalize(spec)
        resolution = resolve(normalized, self.snapshot)
        return compile_plan(resolution, normalized)

    async def apply(self, spec: SessionSpec) -> ApplyResult:
        normalized = normalize(spec)
        resolution = resolve(normalized, self.snapshot)
        plan = compile_plan(resolution, normalized)
        if plan.is_empty:
            return ApplyResult(session_name=spec.name, success=True, steps=[], total_duration_s=0.0)
        ports = SessionPorts(state=self._state, client=self._client)
        return await execute_plan(plan, ports, spec.options)

    async def capture(self, *, name: str | None = None) -> CapturedSession:
        return capture_from_snapshot(self.snapshot, name=name)

    async def close(self) -> None:
        await self._state.close()
        await self._client.close()

    async def __aenter__(self) -> AsyncNirip:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
