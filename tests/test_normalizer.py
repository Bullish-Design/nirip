from nirip.resolve.normalizer import normalize
from nirip.spec.models import AppSpec, MatchRule, SessionSpec, WorkspaceSpec


def test_normalize_basic() -> None:
    app = AppSpec(name="a", match=MatchRule(app_id="x"))
    spec = SessionSpec(
        name="s",
        workspaces=[WorkspaceSpec(name="w", apps=[app])],
    )
    n = normalize(spec)
    assert len(n.apps) == 1
    assert n.app_index["w/a"].name == "a"
