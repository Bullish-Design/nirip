"""Tests for inter-app depends_on wiring in the compiler."""

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


def test_depends_on_enforces_ordering() -> None:
    napp_a = NormalizedApp(
        name="app_a",
        workspace_name="dev",
        match=MatchRule(app_id="app_a"),
        spawn=SpawnSpec(command="app_a"),
        placement=PlacementSpec(),
        optional=False,
        startup_timeout_s=10.0,
        depends_on=[],
    )
    napp_b = NormalizedApp(
        name="app_b",
        workspace_name="dev",
        match=MatchRule(app_id="app_b"),
        spawn=SpawnSpec(command="app_b"),
        placement=PlacementSpec(),
        optional=False,
        startup_timeout_s=10.0,
        depends_on=["app_a"],
    )

    def make_ar(name: str) -> AppResolution:
        return AppResolution(
            app_name=name,
            workspace_name="dev",
            status=ResolutionStatus.MISSING,
            match_decision=MatchDecision(
                app_name=name,
                workspace_name="dev",
                assigned_window_id=None,
                candidates=[],
                confidence=0.0,
                reasons=["test"],
            ),
            drift=[],
        )

    wr = WorkspaceResolution(
        name="dev",
        exists=True,
        output_correct=True,
        desired_output=None,
        current_output=None,
        app_resolutions=[make_ar("app_a"), make_ar("app_b")],
    )
    resolution = Resolution(
        session_name="test",
        workspace_resolutions=[wr],
        warnings=[],
    )
    normalized = NormalizedSession(
        name="test",
        description="",
        options=SessionOptions(),
        workspaces=[NormalizedWorkspace(name="dev", output=None, focus=False, app_names=["app_a", "app_b"])],
        apps=[napp_a, napp_b],
        app_index={"dev/app_a": napp_a, "dev/app_b": napp_b},
    )

    plan = compile_plan(resolution, normalized)

    a_steps = [s for s in plan.steps if s.app_name == "app_a"]
    b_steps = [s for s in plan.steps if s.app_name == "app_b"]
    assert a_steps and b_steps

    a_last = a_steps[-1]
    b_first = b_steps[0]
    assert a_last.id in b_first.depends_on

    step_ids = [s.id for s in plan.steps]
    assert step_ids.index(a_last.id) < step_ids.index(b_first.id)
