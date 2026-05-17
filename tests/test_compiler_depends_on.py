"""Tests for inter-app depends_on wiring in the compiler."""

from nirip.planning.compiler import compile_plan
from nirip.resolve.models import (
    AppResolution,
    MatchTier,
    MatchDecision,
    Resolution,
    ResolutionStatus,
    WorkspaceResolution,
)
from nirip.spec.models import AppSpec, MatchRule, PlacementSpec, SessionOptions, SpawnSpec


def test_depends_on_enforces_ordering() -> None:
    app_a = AppSpec(
        name="app_a",
        match=MatchRule(app_id="app_a"),
        spawn=SpawnSpec(command="app_a"),
        placement=PlacementSpec(),
        optional=False,
        depends_on=[],
        startup_timeout_s=10.0,
    )
    app_b = AppSpec(
        name="app_b",
        match=MatchRule(app_id="app_b"),
        spawn=SpawnSpec(command="app_b"),
        placement=PlacementSpec(),
        optional=False,
        depends_on=["app_a"],
        startup_timeout_s=10.0,
    )

    def make_ar(spec: AppSpec) -> AppResolution:
        return AppResolution(
            app_name=spec.name,
            workspace_name="dev",
            status=ResolutionStatus.MISSING,
            match_decision=MatchDecision(
                app_name=spec.name,
                workspace_name="dev",
                assigned_window_id=None,
                candidates=[],
                tier=MatchTier.NONE,
                reasons=["test"],
            ),
            drift=[],
            spec=spec,
            startup_timeout_s=10.0,
        )

    wr = WorkspaceResolution(
        name="dev",
        exists=True,
        output_correct=True,
        desired_output=None,
        current_output=None,
        focus=False,
        app_resolutions=[make_ar(app_a), make_ar(app_b)],
    )
    resolution = Resolution(
        session_name="test",
        workspace_resolutions=[wr],
        warnings=[],
    )
    plan = compile_plan(resolution, SessionOptions())

    a_steps = [s for s in plan.steps if s.app_name == "app_a"]
    b_steps = [s for s in plan.steps if s.app_name == "app_b"]
    assert a_steps and b_steps

    a_last = a_steps[-1]
    b_first = b_steps[0]
    assert a_last.id in b_first.depends_on

    step_ids = [s.id for s in plan.steps]
    assert step_ids.index(a_last.id) < step_ids.index(b_first.id)
