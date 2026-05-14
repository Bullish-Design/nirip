from nirip.planning.compiler import compile_diff, compile_plan
from nirip.resolve.matcher import evaluate_rule, match_app
from nirip.resolve.normalizer import normalize
from nirip.resolve.resolver import resolve
from nirip.spec.models import AppSpec, MatchRule, SessionSpec, WorkspaceSpec
from tests.conftest import Snap, Win, Ws


def test_evaluate_rule() -> None:
    ok, conf, _ = evaluate_rule(MatchRule(app_id="firefox"), Win(1, "firefox", "Docs", None, 1))
    assert ok
    assert conf == 1.0


def test_match_resolve_plan() -> None:
    spec = SessionSpec(
        name="dev",
        workspaces=[WorkspaceSpec(name="code", apps=[AppSpec(name="docs", match=MatchRule(app_id="firefox"))])],
    )
    snap = Snap(windows={1: Win(1, "firefox", "Docs", None, 2)}, workspaces={2: Ws(2, "other", "DP-1")})

    decision = match_app("docs", "code", MatchRule(app_id="firefox"), list(snap.windows.values()))
    assert decision.best == 1

    norm = normalize(spec)
    res = resolve(norm, snap)
    plan = compile_plan(res)
    diff = compile_diff(res)

    assert res.session_name == "dev"
    assert plan.session_name == "dev"
    assert diff.session_name == "dev"
