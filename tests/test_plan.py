from __future__ import annotations

import pytest

from nirip.plan import StepKind, _parse_size, _topological_sort, build_plan
from nirip.resolve import Resolution, ResolutionStatus, WorkspaceState
from nirip.spec import AppSpec, MatchRule, NiripError, SessionOptions


def _app(name: str, status: ResolutionStatus) -> object:
    from nirip.resolve import AppResolution

    return AppResolution(
        app_name=name,
        workspace_name="code",
        status=status,
        window_id=None,
        is_ambiguous=False,
        drift=[],
        spec=AppSpec(name=name, match=MatchRule(app_id=name), spawn={"command": ["echo", name]}),
        startup_timeout_s=5.0,
    )


def test_parse_size_variants() -> None:
    assert _parse_size(0.5) == (0.5, None)
    assert _parse_size("px:900") == (None, 900)
    with pytest.raises(NiripError):
        _parse_size("px:nope")


def test_build_plan_spawns_and_waits_for_missing() -> None:
    resolution = Resolution(
        session_name="dev",
        workspaces=[
            WorkspaceState(
                name="code",
                exists=True,
                output_correct=True,
                desired_output=None,
                current_output="DP-1",
                focus=False,
            )
        ],
        apps=[_app("firefox", ResolutionStatus.MISSING)],
    )
    plan = build_plan(resolution, SessionOptions())
    kinds = [s.kind for s in plan.steps]
    assert StepKind.SPAWN_WINDOW in kinds
    assert StepKind.WAIT_FOR_WINDOW in kinds
    assert not plan.is_empty


def test_topological_sort_cycle_raises() -> None:
    from nirip.plan import PlanStep

    steps = [
        PlanStep(id="a", kind=StepKind.FOCUS_WORKSPACE, description="a", depends_on=["b"]),
        PlanStep(id="b", kind=StepKind.FOCUS_WORKSPACE, description="b", depends_on=["a"]),
    ]
    with pytest.raises(Exception, match="dependency cycle"):
        _topological_sort(steps)
