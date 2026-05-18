from types import SimpleNamespace

from nirip.planning.compiler import compile_diff, compile_plan
from nirip.resolve.resolver import resolve
from nirip.spec.models import AppSpec, MatchRule, SessionSpec, WorkspaceSpec


def test_pipeline_planning() -> None:
    app = AppSpec(name="a", match=MatchRule(app_id="x"))
    spec = SessionSpec(
        name="s",
        workspaces=[WorkspaceSpec(name="w", apps=[app])],
    )
    window = SimpleNamespace(
        id=1,
        app_id="x",
        title="",
        pid=None,
        workspace_id=None,
        is_floating=False,
        is_fullscreen=False,
        is_maximized=False,
    )
    snap = SimpleNamespace(
        windows={1: window},
        workspaces={1: SimpleNamespace(id=1, name="w", output="DP-1")},
    )
    resolution = resolve(spec, snap)
    plan = compile_plan(resolution, spec.options)
    diff = compile_diff(resolution)
    assert plan.session_name == "s"
    assert diff.session_name == "s"


def test_compile_diff_reports_optional_missing() -> None:
    app = AppSpec(name="a", match=MatchRule(app_id="x"), optional=True)
    spec = SessionSpec(
        name="s",
        workspaces=[WorkspaceSpec(name="w", apps=[app])],
    )
    snap = SimpleNamespace(windows={}, workspaces={})
    resolution = resolve(spec, snap)
    diff = compile_diff(resolution)
    assert diff.optional_missing == ["w/a"]
