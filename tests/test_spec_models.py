import pytest

from nirip.spec.models import AppSpec, MatchRule, PlacementSpec, SessionOptions, SessionSpec, SpawnSpec, WorkspaceSpec


def test_match_rule_requires_criteria() -> None:
    with pytest.raises(ValueError):
        MatchRule()


def test_match_rule_any_alias() -> None:
    rule = MatchRule(any=[MatchRule(app_id="firefox"), MatchRule(app_id="chromium")])
    assert rule.any_of is not None
    assert len(rule.any_of) == 2


def test_placement_conflict() -> None:
    with pytest.raises(ValueError):
        PlacementSpec(floating=True, fullscreen=True)


def test_session_spec_minimal() -> None:
    spec = SessionSpec(name="test", workspaces=[WorkspaceSpec(name="ws1")])
    assert spec.name == "test"


def test_full_spec_shape() -> None:
    spec = SessionSpec(
        name="dev",
        options=SessionOptions(mode="reconcile"),
        workspaces=[
            WorkspaceSpec(
                name="code",
                apps=[
                    AppSpec(
                        name="editor",
                        match=MatchRule(app_id="nvim"),
                        spawn=SpawnSpec(command=["nvim"]),
                    )
                ],
            )
        ],
    )
    assert spec.workspaces[0].apps[0].name == "editor"
