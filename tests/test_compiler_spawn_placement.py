"""Tests that spawned apps get full placement steps."""

from nirip.planning.compiler import compile_plan
from nirip.resolve.models import (
    AppResolution,
    MatchDecision,
    NormalizedApp,
    NormalizedSession,
    NormalizedWorkspace,
    Resolution,
    ResolutionStatus,
    WorkspaceResolution,
)
from nirip.spec.models import MatchRule, PlacementSpec, SessionOptions, SpawnSpec


def _make_resolution(status: ResolutionStatus, wid: int | None = None) -> tuple[Resolution, NormalizedSession]:
    napp = NormalizedApp(
        name="myapp",
        workspace_name="dev",
        match=MatchRule(app_id="myapp"),
        spawn=SpawnSpec(command="myapp"),
        placement=PlacementSpec(floating=True, focus=True),
        optional=False,
        startup_timeout_s=10.0,
        depends_on=[],
    )
    decision = MatchDecision(
        app_name="myapp",
        workspace_name="dev",
        assigned_window_id=wid,
        candidates=[],
        confidence=0.0 if wid is None else 1.0,
        rationale=["test"],
    )
    ar = AppResolution(
        app_name="myapp",
        workspace_name="dev",
        status=status,
        match_decision=decision,
        drift=[],
        action_required=True,
    )
    wr = WorkspaceResolution(
        name="dev",
        exists=True,
        output_correct=True,
        desired_output=None,
        current_output=None,
        app_resolutions=[ar],
    )
    resolution = Resolution(
        session_name="test",
        workspace_resolutions=[wr],
        unmatched_apps=[ar] if status == ResolutionStatus.MISSING else [],
        ambiguous_apps=[],
        warnings=[],
    )
    normalized = NormalizedSession(
        name="test",
        description="",
        options=SessionOptions(),
        workspaces=[NormalizedWorkspace(name="dev", output=None, focus=False, app_names=["myapp"])],
        apps=[napp],
        app_index={"dev/myapp": napp},
    )
    return resolution, normalized


def test_spawned_app_gets_placement_steps() -> None:
    resolution, normalized = _make_resolution(ResolutionStatus.MISSING, wid=None)
    plan = compile_plan(resolution, normalized)

    kinds = [s.kind for s in plan.steps]
    assert "spawn_window" in kinds
    assert "wait_for_window" in kinds
    assert "move_window_to_workspace" in kinds
    assert "set_floating" in kinds
    assert "focus_window" in kinds


def test_spawned_app_placement_has_null_window_id() -> None:
    resolution, normalized = _make_resolution(ResolutionStatus.MISSING, wid=None)
    plan = compile_plan(resolution, normalized)

    float_step = next(s for s in plan.steps if s.kind == "set_floating")
    assert float_step.window_id is None
    assert float_step.app_name == "myapp"


def test_spawned_app_placement_depends_on_wait() -> None:
    resolution, normalized = _make_resolution(ResolutionStatus.MISSING, wid=None)
    plan = compile_plan(resolution, normalized)

    wait_step = next(s for s in plan.steps if s.kind == "wait_for_window")
    float_step = next(s for s in plan.steps if s.kind == "set_floating")
    assert wait_step.id in float_step.depends_on
