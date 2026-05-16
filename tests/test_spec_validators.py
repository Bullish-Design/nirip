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
