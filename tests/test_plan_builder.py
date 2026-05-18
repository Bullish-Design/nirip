from nirip.planning.builder import PlanBuilder
from nirip.planning.compiler import parse_size
from nirip.resolve.models import (
    AppResolution,
    MatchDecision,
    MatchTier,
    Resolution,
    ResolutionStatus,
    WorkspaceResolution,
)
from nirip.spec.models import AppSpec, MatchRule, PlacementSpec, SpawnSpec


def test_plan_builder_wires_app_dependencies() -> None:
    app_a = AppSpec(
        name="a",
        match=MatchRule(app_id="a"),
        spawn=SpawnSpec(command="a"),
        placement=PlacementSpec(floating=False, focus=False),
        depends_on=[],
    )
    app_b = AppSpec(
        name="b",
        match=MatchRule(app_id="b"),
        spawn=SpawnSpec(command="b"),
        placement=PlacementSpec(floating=False, focus=False),
        depends_on=["a"],
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
                reasons=[],
            ),
            drift=[],
            spec=spec,
            startup_timeout_s=5.0,
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
    resolution = Resolution(session_name="s", workspace_resolutions=[wr], warnings=[])

    builder = PlanBuilder(parse_size=parse_size)
    for ar in wr.app_resolutions:
        deps = builder.spawn_app(ar, wr.name, [])
        builder.place_window(ar, wr, deps)
    builder.wire_app_dependencies(resolution)
    steps = builder.build()

    a_steps = [s for s in steps if s.app_name == "a"]
    b_steps = [s for s in steps if s.app_name == "b"]
    assert a_steps and b_steps
    assert a_steps[-1].id in b_steps[0].depends_on
