from types import SimpleNamespace

from nirip.planning.compiler import compile_plan
from nirip.resolve.resolver import resolve
from nirip.spec.models import AppSpec, MatchRule, SessionSpec, WorkspaceSpec


def test_end_to_end_resolution_to_plan() -> None:
    app = AppSpec(name="a", match=MatchRule(app_id="x"))
    spec = SessionSpec(
        name="s",
        workspaces=[WorkspaceSpec(name="w", apps=[app])],
    )
    snapshot = SimpleNamespace(windows={}, workspaces={})
    resolution = resolve(spec, snapshot)
    plan = compile_plan(resolution, spec.options)
    assert plan.session_name == "s"
