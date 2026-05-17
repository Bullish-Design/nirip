from nirip.spec.models import AppSpec, MatchRule, SessionSpec, SpawnSpec, WorkspaceSpec
from nirip.spec.validators import validate_session


def test_validate_duplicate_workspace() -> None:
    spec = SessionSpec(name="s", workspaces=[WorkspaceSpec(name="w"), WorkspaceSpec(name="w")])
    result = validate_session(spec)
    assert not result.valid


def test_validate_spawn_empty() -> None:
    app = AppSpec(
        name="a",
        match=MatchRule(app_id="x"),
        spawn=SpawnSpec(command=""),
    )
    spec = SessionSpec(
        name="s",
        workspaces=[WorkspaceSpec(name="w", apps=[app])],
    )
    result = validate_session(spec)
    assert not result.valid


def test_depends_on_unknown_app_error_message() -> None:
    spec = SessionSpec(
        name="test",
        workspaces=[
            WorkspaceSpec(
                name="dev",
                apps=[
                    AppSpec(name="editor", match=MatchRule(app_id="code"), depends_on=["nonexistent"]),
                ],
            )
        ],
    )
    result = validate_session(spec)
    assert not result.valid
    assert any("does not exist in workspace 'dev'" in e for e in result.errors)
    assert any("cross-workspace dependencies are not supported" in e for e in result.errors)


def test_depends_on_cycle_detected() -> None:
    spec = SessionSpec(
        name="test",
        workspaces=[
            WorkspaceSpec(
                name="dev",
                apps=[
                    AppSpec(name="a", match=MatchRule(app_id="a"), depends_on=["b"]),
                    AppSpec(name="b", match=MatchRule(app_id="b"), depends_on=["a"]),
                ],
            )
        ],
    )
    result = validate_session(spec)
    assert not result.valid
    assert any("dependency cycle" in e for e in result.errors)


def test_dangling_dep_skips_dfs() -> None:
    spec = SessionSpec(
        name="test",
        workspaces=[
            WorkspaceSpec(
                name="dev",
                apps=[
                    AppSpec(name="a", match=MatchRule(app_id="a"), depends_on=["ghost"]),
                    AppSpec(name="b", match=MatchRule(app_id="b"), depends_on=["a"]),
                ],
            )
        ],
    )
    result = validate_session(spec)
    assert not result.valid
    assert any("ghost" in e for e in result.errors)
    assert not any("cycle" in e for e in result.errors)
