from nirip.resolve.normalizer import normalize
from nirip.spec.models import AppSpec, MatchRule, SessionSpec, WorkspaceSpec


def test_basic_normalization() -> None:
    spec = SessionSpec(
        name="test",
        workspaces=[
            WorkspaceSpec(name="code", apps=[AppSpec(name="editor", match=MatchRule(app_id="nvim"))]),
            WorkspaceSpec(name="comms", apps=[AppSpec(name="slack", match=MatchRule(app_id="Slack"))]),
        ],
    )
    norm = normalize(spec)
    assert len(norm.apps) == 2
    assert "code/editor" in norm.app_index
