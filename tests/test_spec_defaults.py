from nirip.spec.defaults import apply_defaults
from nirip.spec.models import AppSpec, MatchRule, SessionOptions, SessionSpec, WorkspaceSpec


def test_defaults_apply_timeout() -> None:
    """When app has no explicit timeout, global default is applied."""
    spec = SessionSpec(
        name="s",
        options=SessionOptions(default_startup_timeout_s=30.0),
        workspaces=[WorkspaceSpec(name="w", apps=[AppSpec(name="a", match=MatchRule(app_id="x"))])],
    )
    out = apply_defaults(spec)
    assert out.workspaces[0].apps[0].startup_timeout_s == 30.0


def test_explicit_timeout_not_overwritten() -> None:
    """When app explicitly sets timeout to 20.0, it must NOT be overwritten."""
    spec = SessionSpec(
        name="s",
        options=SessionOptions(default_startup_timeout_s=30.0),
        workspaces=[
            WorkspaceSpec(
                name="w",
                apps=[AppSpec(name="a", match=MatchRule(app_id="x"), startup_timeout_s=20.0)],
            )
        ],
    )
    out = apply_defaults(spec)
    assert out.workspaces[0].apps[0].startup_timeout_s == 20.0


def test_default_timeout_when_global_is_default() -> None:
    """When no explicit timeout and global is default (20.0), app gets 20.0."""
    spec = SessionSpec(
        name="s",
        workspaces=[WorkspaceSpec(name="w", apps=[AppSpec(name="a", match=MatchRule(app_id="x"))])],
    )
    out = apply_defaults(spec)
    assert out.workspaces[0].apps[0].startup_timeout_s == 20.0
