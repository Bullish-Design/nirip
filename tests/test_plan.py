from __future__ import annotations

import pytest

from nirip.plan import PlanStep, StepKind, _parse_size, _topological_sort, _validate_window_id_contracts, build_plan
from nirip.resolve import DriftItem, DriftKind, Resolution, ResolutionStatus, WorkspaceState
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
    steps = [
        PlanStep(id="a", kind=StepKind.FOCUS_WORKSPACE, description="a", depends_on=["b"]),
        PlanStep(id="b", kind=StepKind.FOCUS_WORKSPACE, description="b", depends_on=["a"]),
    ]
    with pytest.raises(Exception, match="dependency cycle"):
        _topological_sort(steps)


def test_planstep_requires_fields_for_kind() -> None:
    with pytest.raises(ValueError, match="requires command"):
        PlanStep(id="x", kind=StepKind.SPAWN_WINDOW, description="spawn")


def test_build_plan_adds_placement_and_workspace_dependencies() -> None:
    from nirip.resolve import AppResolution

    workspace = WorkspaceState(
        name="code",
        exists=False,
        output_correct=False,
        desired_output="DP-1",
        current_output=None,
        focus=False,
    )
    a = AppResolution(
        app_name="a",
        workspace_name="code",
        status=ResolutionStatus.MISSING,
        window_id=None,
        is_ambiguous=False,
        drift=[],
        spec=AppSpec(name="a", match=MatchRule(app_id="a"), spawn={"command": ["echo", "a"]}),
        startup_timeout_s=5.0,
    )
    b = AppResolution(
        app_name="b",
        workspace_name="code",
        status=ResolutionStatus.DRIFTED,
        window_id=10,
        is_ambiguous=False,
        drift=[DriftItem(kind=DriftKind.WRONG_FLOATING, current="False", desired="True")],
        spec=AppSpec(
            name="b",
            match=MatchRule(app_id="b"),
            placement={"floating": True},
            depends_on=["a"],
            spawn={"command": ["echo", "b"]},
        ),
        startup_timeout_s=5.0,
    )
    resolution = Resolution(session_name="dev", workspaces=[workspace], apps=[a, b])
    plan = build_plan(resolution, SessionOptions())
    kinds = [s.kind for s in plan.steps]
    assert StepKind.CREATE_WORKSPACE in kinds
    assert StepKind.MOVE_WINDOW in kinds
    assert StepKind.SET_STATE in kinds
    first_b = next(s for s in plan.steps if s.app_name == "b")
    last_a = [s.id for s in plan.steps if s.app_name == "a"][-1]
    assert last_a in first_b.depends_on


def test_build_plan_missing_move_depends_on_wait_transitively() -> None:
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
    move = next(s for s in plan.steps if s.kind == StepKind.MOVE_WINDOW and s.app_name == "firefox")
    wait = next(s for s in plan.steps if s.kind == StepKind.WAIT_FOR_WINDOW and s.app_name == "firefox")

    by_id = {s.id: s for s in plan.steps}
    stack = [move.id]
    seen: set[str] = set()
    found = False
    while stack:
        sid = stack.pop()
        if sid in seen:
            continue
        seen.add(sid)
        if sid == wait.id:
            found = True
            break
        stack.extend(by_id[sid].depends_on)
    assert found is True


def test_validate_window_id_contracts_raises_without_wait_dependency() -> None:
    steps = [
        PlanStep(
            id="move-1",
            kind=StepKind.MOVE_WINDOW,
            description="move app",
            app_name="firefox",
            workspace_name="code",
            window_id=None,
            depends_on=[],
        )
    ]
    with pytest.raises(NiripError, match="no window_id and no WAIT_FOR_WINDOW"):
        _validate_window_id_contracts(steps)
