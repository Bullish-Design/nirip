from nirip.spec.models import AppSpec, MatchRule, SessionSpec, SpawnSpec, WorkspaceSpec
from nirip.spec.validators import validate_session


def _spec(workspaces: list[WorkspaceSpec]) -> SessionSpec:
    return SessionSpec(name="test", workspaces=workspaces)


def test_duplicate_workspace_names() -> None:
    result = validate_session(_spec([WorkspaceSpec(name="code"), WorkspaceSpec(name="code")]))
    assert not result.valid


def test_duplicate_app_names() -> None:
    result = validate_session(
        _spec(
            [
                WorkspaceSpec(
                    name="code",
                    apps=[
                        AppSpec(name="a", match=MatchRule(app_id="one")),
                        AppSpec(name="a", match=MatchRule(app_id="two")),
                    ],
                )
            ]
        )
    )
    assert not result.valid


def test_dangling_depends_on() -> None:
    result = validate_session(
        _spec(
            [
                WorkspaceSpec(
                    name="code",
                    apps=[AppSpec(name="term", match=MatchRule(app_id="t"), depends_on=["editor"])],
                )
            ]
        )
    )
    assert not result.valid


def test_invalid_regex() -> None:
    result = validate_session(
        _spec(
            [
                WorkspaceSpec(
                    name="code",
                    apps=[AppSpec(name="a", match=MatchRule(title_regex="[bad"))],
                )
            ]
        )
    )
    assert not result.valid


def test_weak_matcher_warning() -> None:
    result = validate_session(
        _spec(
            [
                WorkspaceSpec(
                    name="code",
                    apps=[AppSpec(name="a", match=MatchRule(title_regex="docs"))],
                )
            ]
        )
    )
    assert result.valid
    assert result.warnings


def test_empty_spawn_command() -> None:
    result = validate_session(
        _spec(
            [
                WorkspaceSpec(
                    name="code",
                    apps=[
                        AppSpec(name="a", match=MatchRule(app_id="x"), spawn=SpawnSpec(command=[])),
                    ],
                )
            ]
        )
    )
    assert not result.valid
