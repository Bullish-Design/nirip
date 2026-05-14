"""Async nirip facade."""
from __future__ import annotations

from typing import Any

from nirip.capture.capturer import CapturedSession, capture_from_snapshot
from nirip.config import NiripConfig
from nirip.execution.executor import PlanExecutor
from nirip.execution.models import ApplyResult
from nirip.planning.compiler import compile_diff, compile_plan
from nirip.planning.models import Plan, SessionDiff
from nirip.resolve.normalizer import normalize
from nirip.resolve.resolver import resolve
from nirip.spec.models import SessionSpec


class AsyncNirip:
    """Primary async API facade."""

    def __init__(self, config: NiripConfig | None = None, *, snapshot: Any | None = None) -> None:
        self.config = config or NiripConfig()
        self._snapshot = snapshot
        self._executor = PlanExecutor(client=None)

    @classmethod
    async def open(cls, config: NiripConfig | None = None) -> AsyncNirip:
        return cls(config=config)

    def bind_snapshot(self, snapshot: Any) -> None:
        """Bind a snapshot-like object used for local planning/execution."""

        self._snapshot = snapshot

    async def diff(self, spec: SessionSpec) -> SessionDiff:
        normalized = normalize(spec)
        resolved = resolve(normalized, self._require_snapshot())
        return compile_diff(resolved)

    async def plan(self, spec: SessionSpec) -> Plan:
        normalized = normalize(spec)
        resolved = resolve(normalized, self._require_snapshot())
        return compile_plan(resolved)

    async def apply(self, spec: SessionSpec) -> ApplyResult:
        plan = await self.plan(spec)
        return await self._executor.execute(plan, snapshot=self._snapshot)

    async def capture(self, *, name: str | None = None) -> CapturedSession:
        return capture_from_snapshot(self._require_snapshot(), name=name)

    async def inspect(self) -> Any:
        return self._require_snapshot()

    async def doctor(self, spec: SessionSpec | None = None) -> dict[str, Any]:
        report: dict[str, Any] = {"connected": self._snapshot is not None, "warnings": [], "errors": []}
        if spec is not None:
            diff = await self.diff(spec)
            report["warnings"].extend(diff.warnings)
            report["errors"].extend(diff.errors)
        return report

    async def close(self) -> None:
        return None

    def _require_snapshot(self) -> Any:
        if self._snapshot is None:
            raise RuntimeError("No snapshot bound; integrate AsyncNirip.open with niri-state to use live mode")
        return self._snapshot

    async def __aenter__(self) -> AsyncNirip:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        await self.close()
