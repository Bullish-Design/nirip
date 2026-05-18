"""nirip: Declarative session reconciler for Niri."""

from __future__ import annotations

import asyncio
from pathlib import Path

from nirip.execute import ApplyResult, SessionPorts, execute_plan
from nirip.plan import Plan, build_plan
from nirip.resolve import Resolution, resolve
from nirip.spec import NiripError, SessionSpec, ValidationError, load_from_file

__all__ = [
    "NiripError",
    "ValidationError",
    "SessionSpec",
    "Resolution",
    "Plan",
    "ApplyResult",
    "load_from_file",
    "resolve",
    "build_plan",
    "execute_plan",
    "apply_session",
]


def apply_session(path: str | Path) -> ApplyResult:
    """One-shot sync: load -> resolve -> plan -> execute."""
    from niri_pypc import NiriClient
    from niri_state import NiriState

    spec, _ = load_from_file(path)

    async def _run() -> ApplyResult:
        state = await NiriState.open()
        client = NiriClient.create()
        try:
            resolution = resolve(spec, state.snapshot)
            plan = build_plan(resolution, spec.options)
            if plan.is_empty:
                return ApplyResult(session_name=spec.name, success=True, steps=[], total_duration_s=0.0)
            ports = SessionPorts(state=state, client=client)
            return await execute_plan(plan, ports, spec.options)
        finally:
            await state.close()
            await client.close()

    return asyncio.run(_run())
