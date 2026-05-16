from types import SimpleNamespace

from nirip.planning.compiler import compile_plan
from nirip.resolve.normalizer import normalize
from nirip.resolve.resolver import resolve
from nirip.spec.models import AppSpec, MatchRule, SessionSpec, WorkspaceSpec


def test_end_to_end_resolution_to_plan() -> None:
    app = AppSpec(name="a", match=MatchRule(app_id="x"))
    spec = SessionSpec(
        name="s",
        workspaces=[WorkspaceSpec(name="w", apps=[app])],
    )
    normalized = normalize(spec)
    snapshot = SimpleNamespace(windows={}, workspaces={})
    resolution = resolve(normalized, snapshot)
    plan = compile_plan(resolution, normalized)
    assert plan.session_name == "s"
