"""Tests that spawned apps get full placement steps."""

from nirip.planning.compiler import compile_plan
from nirip.planning.models import SetWindowStateStep, WindowProperty
from nirip.resolve.models import (
    AppResolution,
    MatchDecision,
    MatchTier,
    Resolution,
    ResolutionStatus,
    WorkspaceResolution,
)
from nirip.spec.models import AppSpec, MatchRule, PlacementSpec, SessionOptions, SpawnSpec


def _make_resolution(
    status: ResolutionStatus,
    wid: int | None = None,
    placement: PlacementSpec | None = None,
) -> tuple[Resolution, SessionOptions]:
    placement_spec = placement or PlacementSpec(floating=True, focus=True)
    app_spec = AppSpec(
        name="myapp",
        match=MatchRule(app_id="myapp"),
        spawn=SpawnSpec(command="myapp"),
        placement=placement_spec,
        optional=False,
        depends_on=[],
        startup_timeout_s=10.0,
    )
    decision = MatchDecision(
        app_name="myapp",
        workspace_name="dev",
        assigned_window_id=wid,
        candidates=[],
        tier=MatchTier.NONE if wid is None else MatchTier.EXACT,
        reasons=["test"],
    )
    ar = AppResolution(
        app_name="myapp",
        workspace_name="dev",
        status=status,
        match_decision=decision,
        drift=[],
        spec=app_spec,
        startup_timeout_s=10.0,
    )
    wr = WorkspaceResolution(
        name="dev",
        exists=True,
        output_correct=True,
        desired_output=None,
        current_output=None,
        focus=False,
        app_resolutions=[ar],
    )
    resolution = Resolution(
        session_name="test",
        workspace_resolutions=[wr],
        warnings=[],
    )
    options = SessionOptions()
    return resolution, options


def test_spawned_app_gets_placement_steps() -> None:
    resolution, options = _make_resolution(ResolutionStatus.MISSING, wid=None)
    plan = compile_plan(resolution, options)

    kinds = [s.kind for s in plan.steps]
    assert "spawn_window" in kinds
    assert "wait_for_window" in kinds
    assert "move_window_to_workspace" in kinds
    assert "set_window_state" in kinds
    assert "focus_window" in kinds


def test_spawned_app_placement_has_null_window_id() -> None:
    resolution, options = _make_resolution(ResolutionStatus.MISSING, wid=None)
    plan = compile_plan(resolution, options)

    state_step = next(
        s
        for s in plan.steps
        if isinstance(s, SetWindowStateStep) and s.property == WindowProperty.FLOATING
    )
    assert state_step.window_id is None
    assert state_step.app_name == "myapp"


def test_spawned_app_placement_depends_on_wait() -> None:
    resolution, options = _make_resolution(ResolutionStatus.MISSING, wid=None)
    plan = compile_plan(resolution, options)

    wait_step = next(s for s in plan.steps if s.kind == "wait_for_window")
    state_step = next(
        s
        for s in plan.steps
        if isinstance(s, SetWindowStateStep) and s.property == WindowProperty.FLOATING
    )
    assert wait_step.id in state_step.depends_on


def test_spawned_app_default_placement_skips_state_steps() -> None:
    resolution, options = _make_resolution(
        ResolutionStatus.MISSING,
        wid=None,
        placement=PlacementSpec(floating=False, fullscreen=False, maximized=False),
    )
    plan = compile_plan(resolution, options)
    assert all(step.kind != "set_window_state" for step in plan.steps)


def test_spawned_app_non_default_state_is_emitted() -> None:
    resolution, options = _make_resolution(
        ResolutionStatus.MISSING,
        wid=None,
        placement=PlacementSpec(floating=False, fullscreen=True, maximized=False),
    )
    plan = compile_plan(resolution, options)
    fullscreen_steps = [
        step
        for step in plan.steps
        if isinstance(step, SetWindowStateStep) and step.property == WindowProperty.FULLSCREEN
    ]
    assert len(fullscreen_steps) == 1
