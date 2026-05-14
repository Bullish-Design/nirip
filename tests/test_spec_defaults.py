from nirip.spec.defaults import apply_defaults
from nirip.spec.models import AppSpec, MatchRule, SessionOptions, SessionSpec, WorkspaceSpec


def test_defaults_apply_timeout() -> None:
    spec = SessionSpec(
        name="s",
        options=SessionOptions(default_startup_timeout_s=30.0),
        workspaces=[WorkspaceSpec(name="w", apps=[AppSpec(name="a", match=MatchRule(app_id="x"))])],
    )
    out = apply_defaults(spec)
    assert out.workspaces[0].apps[0].startup_timeout_s == 30.0
