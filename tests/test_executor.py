import asyncio
from types import SimpleNamespace

from nirip.execution.executor import execute_plan
from nirip.execution.handlers import execute_step
from nirip.execution.models import SessionPorts
from nirip.execution.runtime import AppRuntimeState, SessionRuntime
from nirip.planning.models import FocusWorkspaceStep, Plan, WaitForWindowStep
from nirip.resolve.models import Resolution
from nirip.spec.models import MatchRule, SessionOptions


class DummyState:
    def __init__(self) -> None:
        self.snapshot = SimpleNamespace(workspaces={}, windows={})


class DummyClient:
    async def request(self, _req):
        return None


def test_execute_plan_basic() -> None:
    resolution = Resolution(
        session_name="s",
        workspace_resolutions=[],
        unmatched_apps=[],
        ambiguous_apps=[],
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
            SessionPorts(state=DummyState(), client=DummyClient()),
            SessionOptions(),
        )
    )
    assert len(result.steps) == 1


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
    result = asyncio.run(execute_step(step, SessionPorts(state=state, client=DummyClient()), runtime))
    assert result.window_id == 42
    assert runtime.apps["myapp"].matched_window_id == 42
