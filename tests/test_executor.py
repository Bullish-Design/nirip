import asyncio
from typing import Any

from nirip.execution.actions import StepAction
from nirip.execution.executor import PlanExecutor
from nirip.execution.models import StepOutcome
from nirip.planning.models import Plan, PlanStep, StepKind
from nirip.resolve.models import Resolution
from tests.conftest import Snap, Win, Ws


class MockClient:
    def __init__(self, *, fail_on: set[str] | None = None) -> None:
        self.requests: list[StepAction] = []
        self.fail_on = fail_on or set()

    async def request(self, payload: StepAction) -> Any:
        self.requests.append(payload)
        if payload.kind in self.fail_on:
            raise RuntimeError(f"simulated failure: {payload.kind}")
        return {"ok": True}


def _empty_resolution() -> Resolution:
    return Resolution(
        session_name="test",
        workspace_resolutions=[],
        unmatched_apps=[],
        ambiguous_apps=[],
        warnings=[],
    )


def _plan(*steps: PlanStep) -> Plan:
    return Plan(session_name="test", steps=list(steps), resolution=_empty_resolution())


def _step(id: str, kind: StepKind, **kwargs: Any) -> PlanStep:
    return PlanStep(id=id, kind=kind, description=f"test {id}", **kwargs)


class TestExecutor:
    def test_empty_plan(self) -> None:
        executor = PlanExecutor()
        result = asyncio.run(executor.execute(_plan()))
        assert result.success
        assert result.steps == []

    def test_spawn_not_skipped_with_existing_windows(self) -> None:
        snap = Snap(windows={1: Win(1, "firefox")}, workspaces={1: Ws(1, "code")})
        step = _step("s1", StepKind.SPAWN_WINDOW, app_name="editor")
        executor = PlanExecutor()
        result = asyncio.run(executor.execute(_plan(step), snapshot=snap))
        assert result.steps[0].outcome == StepOutcome.COMPLETED

    def test_wait_for_window_not_skipped(self) -> None:
        snap = Snap(windows={1: Win(1, "firefox")}, workspaces={1: Ws(1, "ws")})
        step = _step("w1", StepKind.WAIT_FOR_WINDOW, app_name="editor")
        executor = PlanExecutor()
        result = asyncio.run(executor.execute(_plan(step), snapshot=snap))
        assert result.steps[0].outcome == StepOutcome.COMPLETED

    def test_ensure_workspace_skipped_when_exists(self) -> None:
        snap = Snap(workspaces={1: Ws(1, "code")})
        step = _step("ws1", StepKind.ENSURE_WORKSPACE, workspace_name="code")
        executor = PlanExecutor()
        result = asyncio.run(executor.execute(_plan(step), snapshot=snap))
        assert result.steps[0].outcome == StepOutcome.SKIPPED

    def test_ensure_workspace_not_skipped_when_missing(self) -> None:
        snap = Snap(workspaces={1: Ws(1, "other")})
        step = _step("ws1", StepKind.ENSURE_WORKSPACE, workspace_name="code")
        executor = PlanExecutor()
        result = asyncio.run(executor.execute(_plan(step), snapshot=snap))
        assert result.steps[0].outcome == StepOutcome.COMPLETED

    def test_client_failure_recorded(self) -> None:
        client = MockClient(fail_on={"spawn_window"})
        step = _step("s1", StepKind.SPAWN_WINDOW, app_name="editor")
        executor = PlanExecutor(client=client)
        result = asyncio.run(executor.execute(_plan(step)))
        assert result.steps[0].outcome == StepOutcome.FAILED
        assert not result.success

    def test_stop_on_error(self) -> None:
        client = MockClient(fail_on={"spawn_window"})
        s1 = _step("s1", StepKind.SPAWN_WINDOW, app_name="a")
        s2 = _step("s2", StepKind.SPAWN_WINDOW, app_name="b")
        executor = PlanExecutor(client=client)
        result = asyncio.run(executor.execute(_plan(s1, s2), stop_on_error=True))
        assert len(result.steps) == 1

    def test_continue_on_error_default(self) -> None:
        client = MockClient(fail_on={"spawn_window"})
        s1 = _step("s1", StepKind.SPAWN_WINDOW, app_name="a")
        s2 = _step("s2", StepKind.ENSURE_WORKSPACE, workspace_name="ws")
        executor = PlanExecutor(client=client)
        result = asyncio.run(executor.execute(_plan(s1, s2)))
        assert len(result.steps) == 2
