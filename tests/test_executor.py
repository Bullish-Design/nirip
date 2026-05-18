import asyncio
from asyncio.subprocess import Process as AsyncProcess
from types import SimpleNamespace
from typing import cast

from niri_pypc import NiriClient
from niri_state import NiriState

from nirip.execution.executor import execute_plan
from nirip.execution.handlers import execute_step
from nirip.execution.hooks import ExecutionHook
from nirip.execution.models import ApplyResult, SessionPorts, StepResult
from nirip.execution.runtime import AppRuntimeState, SessionRuntime
from nirip.planning.models import FocusWorkspaceStep, Plan, PlanStep, WaitForWindowStep
from nirip.resolve.models import Resolution
from nirip.spec.models import MatchRule, SessionOptions


class DummyState:
    def __init__(self) -> None:
        self.snapshot = SimpleNamespace(workspaces={}, windows={})


class DummyClient:
    async def request(self, _req):
        return None


def make_ports(state: DummyState | None = None) -> SessionPorts:
    test_state = state or DummyState()
    return SessionPorts(
        state=cast(NiriState, test_state),
        client=cast(NiriClient, DummyClient()),
    )


class RecordingHook(ExecutionHook):
    def __init__(self) -> None:
        self.events: list[str] = []

    def on_step_start(self, step: PlanStep) -> None:
        self.events.append(f"start:{step.id}")

    def on_step_complete(self, step: PlanStep, result: StepResult) -> None:
        self.events.append(f"done:{step.id}:{result.outcome.value}")

    def on_plan_complete(self, result: ApplyResult) -> None:
        self.events.append(f"plan:{result.success}")


def test_execute_plan_basic() -> None:
    resolution = Resolution(
        session_name="s",
        workspace_resolutions=[],
        warnings=[],
    )
    plan = Plan(
        session_name="s",
        steps=[FocusWorkspaceStep(id="1", description="focus", workspace_name="w")],
        resolution=resolution,
    )
    result = asyncio.run(
        execute_plan(
            plan,
            make_ports(),
            SessionOptions(),
        )
    )
    assert len(result.steps) == 1


def test_execute_plan_reports_hook_events() -> None:
    resolution = Resolution(
        session_name="s",
        workspace_resolutions=[],
        warnings=[],
    )
    plan = Plan(
        session_name="s",
        steps=[FocusWorkspaceStep(id="1", description="focus", workspace_name="w")],
        resolution=resolution,
    )
    hook = RecordingHook()
    _result = asyncio.run(
        execute_plan(
            plan,
            make_ports(),
            SessionOptions(),
            hook=hook,
        )
    )
    assert hook.events == ["start:1", "done:1:completed", "plan:True"]


def test_wait_step_captures_window_id(monkeypatch) -> None:
    window = SimpleNamespace(id=42, app_id="myapp", title="My App", pid=None)
    state = DummyState()
    state.snapshot = SimpleNamespace(windows={42: window}, workspaces={})

    async def fake_wait(_state, predicate, _timeout):
        assert predicate(state.snapshot) is True
        return state.snapshot

    monkeypatch.setattr("nirip.execution.handlers._wait", fake_wait)
    step = WaitForWindowStep(
        id="wait-1",
        description="wait for app",
        app_name="myapp",
        workspace_name="w",
        match=MatchRule(app_id="myapp"),
        timeout_s=1.0,
    )
    runtime = SessionRuntime(
        session_name="s",
        apps={"myapp": AppRuntimeState(app_name="myapp", workspace_name="w")},
    )
    result = asyncio.run(execute_step(step, make_ports(state), runtime))
    assert result.window_id == 42
    assert runtime.apps["myapp"].matched_window_id == 42


def test_wait_step_fails_fast_if_spawned_process_exits(monkeypatch) -> None:
    state = DummyState()

    async def fake_wait(_state, _predicate, _timeout):
        await asyncio.sleep(0.1)
        return state.snapshot

    class FakeProcess:
        async def wait(self) -> int:
            return 3

    monkeypatch.setattr("nirip.execution.handlers._wait", fake_wait)
    step = WaitForWindowStep(
        id="wait-2",
        description="wait for app",
        app_name="myapp",
        workspace_name="w",
        match=MatchRule(app_id="myapp"),
        timeout_s=1.0,
    )
    runtime = SessionRuntime(
        session_name="s",
        apps={
            "myapp": AppRuntimeState(
                app_name="myapp",
                workspace_name="w",
                spawned=True,
                spawn_pid=123,
            )
        },
    )
    runtime.apps["myapp"].spawn_process = cast(AsyncProcess, FakeProcess())
    result = asyncio.run(execute_step(step, make_ports(state), runtime))
    assert result.outcome.value == "failed"
    assert result.message == "process exited with code 3 before window appeared"
