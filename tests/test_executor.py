import asyncio
from types import SimpleNamespace

from nirip.execution.executor import execute_plan
from nirip.execution.models import SessionPorts
from nirip.planning.models import FocusWorkspaceStep, Plan
from nirip.resolve.models import Resolution
from nirip.spec.models import SessionOptions


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
